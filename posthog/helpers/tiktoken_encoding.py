"""Lazy cached access to tiktoken encodings.

Tiktoken may download and verify encoding blobs on first use. Centralizing
access avoids duplicate lazy-load logic and keeps import-time failures from
transient hash mismatches out of unrelated modules.
"""

from __future__ import annotations

import functools

import tiktoken

# Use with ``get_tiktoken_encoding_for_model`` when callers previously used
# ``get_encoding("cl100k_base")`` (embeddings, GPT-4-family text tokenization).
CL100K_BASE_PROXY_MODEL = "gpt-4"


@functools.cache
def get_tiktoken_encoding_for_model(model: str) -> tiktoken.Encoding:
    return tiktoken.encoding_for_model(model)
