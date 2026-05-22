"""Lazy cached access to tiktoken encodings.

Tiktoken may download and verify encoding blobs on first use. Centralizing
access avoids duplicate lazy-load logic and keeps import-time failures from
transient hash mismatches out of unrelated modules.

Use two proxy model names only:
- LLM-facing token counts → ``gpt-4o`` (``o200k_base`` in tiktoken).
- Embedding-facing token counts → ``text-embedding-3-small`` (``cl100k_base``).
"""

from __future__ import annotations

import functools

import tiktoken

# OpenAI chat / completion-style counting (o200k_base).
LLM_TOKEN_COUNT_PROXY_MODEL = "gpt-4o"

# text-embedding-3-* API counting (cl100k_base).
TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL = "text-embedding-3-small"


@functools.cache
def get_tiktoken_encoding_for_model(model: str) -> tiktoken.Encoding:
    return tiktoken.encoding_for_model(model)
