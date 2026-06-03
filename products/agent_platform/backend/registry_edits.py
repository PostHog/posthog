"""
Structured edit primitives for the Tools & Skills registry.

The concierge agent — and a human via the registry UI — both express
template changes as a list of `{ "old": <str>, "new": <str> }` edits
applied sequentially against the current body / source. Each `old`
must match exactly once in the working text; partial regenerations
that can't be located cleanly bail out with a precise error pointing
at the offending edit.

This is the same pattern `LLMSkill.apply_skill_body_edits` uses on
the ai_observability side — extracted here as a small reusable shape
so the skill-template and custom-tool-template viewsets can share it.

See `docs/agent-platform/plans/skill-templates.md` for the wider plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StructuredEditError(Exception):
    """One edit could not be applied. `edit_index` points at the offender.

    Catches the `LLMSkill` shape — single error class for both
    "no match" and "ambiguous match" so the viewset can surface a
    consistent 400 to MCP clients.
    """

    message: str
    edit_index: int | None = None


def apply_structured_edits(text: str, edits: list[dict[str, Any]]) -> str:
    """Apply sequential find/replace edits to `text`.

    Each `edits[i]` is a dict with `old` and `new` string fields. The
    `old` text must match exactly once in the current (partially-edited)
    body — zero matches or multiple matches both raise
    `StructuredEditError` carrying the edit index.

    Edits are applied **in order**. Earlier edits affect what later
    edits' `old` patterns will match against, by design — chain edits
    can rely on the intermediate state.

    Empty edit list returns `text` unchanged.
    """
    result = text
    for i, edit in enumerate(edits):
        try:
            old = edit["old"]
            new = edit["new"]
        except KeyError as exc:
            raise StructuredEditError(
                message=f"Edit {i} missing required field {exc.args[0]!r}; expected {{'old': str, 'new': str}}.",
                edit_index=i,
            ) from exc
        if not isinstance(old, str) or not isinstance(new, str):
            raise StructuredEditError(
                message=f"Edit {i} fields must be strings; got old={type(old).__name__}, new={type(new).__name__}.",
                edit_index=i,
            )
        count = result.count(old)
        if count == 0:
            raise StructuredEditError(
                message=(
                    f"Edit {i}: the 'old' text was not found in the current body. "
                    "If you're chaining edits, remember each edit sees the result of the prior ones."
                ),
                edit_index=i,
            )
        if count > 1:
            raise StructuredEditError(
                message=(
                    f"Edit {i}: the 'old' text matches {count} times — provide more surrounding context "
                    "so the replacement target is unambiguous."
                ),
                edit_index=i,
            )
        result = result.replace(old, new, 1)
    return result
