"""Sanitize user-controlled text before embedding it in an LLM prompt.

Shared across products (subscriptions, marketing analytics, Max tools).
"""

from __future__ import annotations

import re
import unicodedata

INSIGHT_NAME_MAX_LEN = 120
INSIGHT_DESCRIPTION_MAX_LEN = 500
SERIES_LABEL_MAX_LEN = 200
SUBSCRIPTION_TITLE_MAX_LEN = 200
GENERIC_VALUE_MAX_LEN = 200
PROMPT_GUIDE_MAX_LEN = 500
# `CoreMemory.formatted_text` returns `text[:2500] + "…" + text[-2500:]` when the
# raw text exceeds 5000 chars — that's 5001 chars total. Match what the upstream
# helper can actually produce so we don't silently drop the last tail character.
CORE_MEMORY_MAX_LEN = 5001

_TAG_RE = re.compile(r"</?[a-zA-Z_][^>]*>")
_LLM_MARKER_RE = re.compile(
    r"</?\s*(?:"
    r"system|user|assistant|human|insight_data|user_context|subscription_title|core_memory"
    # AI subscription synthesis prompt framing tags — sanitize so a crafted event name
    # or prompt can't escape the `<user_prompt>` / `<project_context>` / `<plan_intent>` /
    # `<query_results>` envelope and inject instruction-shaped content into the LLM context.
    r"|user_prompt|project_context|plan_intent|query_results"
    r")\b[^>]*>?",
    re.IGNORECASE,
)
_NEWLINE_RE = re.compile(r"[\r\n\u2028\u2029]+")
_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")

_INVISIBLE_KEEP = {"\n", "\r", "\t"}
_EXTRA_INVISIBLES = (
    {"\u034f", "\u3164", "\uffa0"}
    | {chr(c) for c in range(0x115F, 0x1161)}
    | {chr(c) for c in range(0x17B4, 0x17B6)}
    | {chr(c) for c in range(0x180B, 0x180E)}
    | {chr(c) for c in range(0xFE00, 0xFE10)}
    | {chr(c) for c in range(0xE0100, 0xE01F0)}
)


def _is_invisible(c: str) -> bool:
    if c in _INVISIBLE_KEEP:
        return False
    if unicodedata.category(c) in ("Cc", "Cf"):
        return True
    return c in _EXTRA_INVISIBLES


def _strip_invisible(value: str) -> str:
    return "".join(c for c in value if not _is_invisible(c))


def sanitize_user_text(
    value: str | None,
    max_len: int,
    *,
    none_placeholder: str = "",
    truncate_marker: str = "",
) -> str:
    if not value:
        return none_placeholder
    cleaned = _strip_invisible(value)
    previous = ""
    while previous != cleaned:
        previous = cleaned
        cleaned = _LLM_MARKER_RE.sub("", cleaned)
        cleaned = _TAG_RE.sub("", cleaned)
    cleaned = _NEWLINE_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return none_placeholder
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + truncate_marker
    return cleaned


def sanitize_core_memory_text(value: str | None, max_len: int = CORE_MEMORY_MAX_LEN) -> str:
    """Sanitize core memory facts. Preserves newlines so each fact stays on its own line,
    but strips structural LLM markers so the memory cannot escape its `<core_memory>` wrapper.
    Core-memory-defaulted alias of `strip_llm_framing_markers` — identical operation."""
    return strip_llm_framing_markers(value, max_len)


def strip_llm_framing_markers(value: str | None, max_len: int) -> str:
    """Strip invisible characters and structural LLM framing tags (e.g. `</query_results>`,
    `<system>`) while PRESERVING newlines and markdown layout. Use for already-formatted content —
    query results, core-memory facts — that must keep its structure but must not be able to break
    out of its framing envelope and inject instruction-shaped content into an LLM prompt.

    Contrast with `sanitize_user_text`, which also collapses newlines and strips all tags: right for
    short single-line values (names, labels) but destructive to a formatted block like a table."""
    if not value:
        return ""
    cleaned = _strip_invisible(value)
    previous = ""
    while previous != cleaned:
        previous = cleaned
        cleaned = _LLM_MARKER_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned
