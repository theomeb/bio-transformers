"""
This script defines a class which inherits from the TransformersWrapper class, and is
specific to the ESM model developed by FAIR (https://github.com/facebookresearch/esm).
"""
from typing import Dict, List, Tuple

import esm
import torch
from biotransformers.wrappers.transformers_wrappers import (
    TransformersModelProperties,
    TransformersWrapper,
)
from torch.nn import DataParallel

# List all ESM models
esm_list = [
    # "esm1_t34_670M_UR50S",
    # "esm1_t34_670M_UR50D",
    "esm1_t34_670M_UR100",
    # "esm1_t12_85M_UR50S",
    "esm1_t6_43M_UR50S",
    "esm1b_t33_650M_UR50S",
    # "esm_msa1_t12_100M_UR50S",
]

# Define a default ESM model
DEFAULT_MODEL = "esm1_t34_670M_UR100"


class ESMWrapper(TransformersWrapper):
    """
    Class that uses an ESM type of pretrained transformers model to evaluate
    a protein likelihood so as other insights.
    """

    def __init__(self, model_dir: str, device, multi_gpu):

        if model_dir not in esm_list:
            print(
                f"Model dir '{model_dir}' not recognized. "
                f"Using '{DEFAULT_MODEL}' as default"
            )
            model_dir = DEFAULT_MODEL

        super().__init__(model_dir, _device=device, multi_gpu=multi_gpu)

        self.model, self.alphabet = esm.pretrained.load_model_and_alphabet(model_dir)
        self.num_layers = self.model.num_layers
        self.hidden_size = self.model.args.embed_dim
        if self.multi_gpu:
            self.model = DataParallel(self.model).to(self._device)
        else:
            self.model = self.model.to(self._device)
        self.batch_converter = self.alphabet.get_batch_converter()

    @property
    def clean_model_id(self) -> str:
        """Clean model ID (in case the model directory is not)"""
        return self.model_id

    @property
    def model_property(self) -> TransformersModelProperties:
        """Returns a class with model properties"""
        return TransformersModelProperties(
            num_sep_tokens=1, begin_token=True, end_token=False
        )

    @property
    def model_vocab_tokens(self) -> List[str]:
        """List of all vocabulary tokens to consider (as strings), which may be a subset
        of the model vocabulary (based on self.vocab_token_list)"""
        voc = (
            self.vocab_token_list
            if self.vocab_token_list is not None
            else self.alphabet.all_toks
        )
        return voc

    @property
    def model_vocabulary(self) -> List[str]:
        """Returns the whole vocabulary list"""
        return list(self.alphabet.tok_to_idx.keys())

    @property
    def vocab_size(self) -> int:
        """Returns the whole vocabulary size"""
        return len(list(self.alphabet.tok_to_idx.keys()))

    @property
    def model_vocab_ids(self) -> List[int]:
        """List of all vocabulary IDs to consider (as ints), which may be a subset
        of the model vocabulary (based on self.vocab_token_list)"""
        return [self.token_to_id(tok) for tok in self.model_vocab_tokens]

    @property
    def mask_token(self) -> str:
        """Representation of the mask token (as a string)"""
        return self.alphabet.all_toks[self.alphabet.mask_idx]  # "<mask>"

    @property
    def pad_token(self) -> str:
        """Representation of the pad token (as a string)"""
        return self.alphabet.all_toks[self.alphabet.padding_idx]  # "<pad>"

    @property
    def begin_token(self) -> str:
        """Representation of the beginning of sentence token (as a string)"""
        return "<cls>"

    @property
    def end_token(self) -> str:
        """Representation of the end of sentence token (as a string). This token doesn't
        exist in the case of ESM, thus we return an empty string."""
        return ""

    @property
    def token_to_id(self):
        """Returns a function which maps tokens to IDs"""
        return lambda x: self.alphabet.tok_to_idx[x]

    @property
    def embeddings_size(self):
        """Returns size of the embeddings"""
        return self.hidden_size

    def _process_sequences_and_tokens(
        self, sequences_list: List[str], tokens_list: List[str]
    ) -> Tuple[Dict[str, torch.tensor], torch.tensor, List[int]]:
        """Function to transform tokens string to IDs; it depends on the model used"""
        tokens = []
        for token in tokens_list:
            if token not in self.model_vocabulary:
                print("Warnings; token", token, "does not belong to model vocabulary")
            else:
                tokens.append(self.token_to_id(token))

        _, _, all_tokens = self.batch_converter(
            [("", sequence) for sequence in sequences_list]
        )

        all_tokens = all_tokens.to("cpu")

        encoded_inputs = {
            "input_ids": all_tokens,
            "attention_mask": 1 * (all_tokens != self.token_to_id(self.pad_token)),
            "token_type_ids": torch.zeros(all_tokens.shape),
        }
        return encoded_inputs, all_tokens, tokens

    def _model_pass(
        self, model_inputs: Dict[str, torch.tensor]
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Function which computes logits and embeddings based on a list of sequences,
        a provided batch size and an inference configuration. The output is obtained
        by computing a forward pass through the model ("forward inference")

        Args:
            model_inputs (Dict[str, torch.tensor]): [description]

        Returns:
            Tuple[torch.tensor, torch.tensor]:
                    * logits [num_seqs, max_len_seqs, vocab_size]
                    * embeddings [num_seqs, max_len_seqs+1, embedding_size]
        """
        last_layer = self.num_layers - 1
        with torch.no_grad():
            model_outputs = self.model(
                model_inputs["input_ids"].to(self._device), repr_layers=[last_layer]
            )

            logits = model_outputs["logits"].detach().cpu()
            embeddings = model_outputs["representations"][last_layer].detach().cpu()

        return logits, embeddings
