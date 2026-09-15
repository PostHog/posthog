"""Map a finished pipeline run onto the eval outcome vocabulary."""

from __future__ import annotations

from typing import Any

from products.conversations.evals.constants import (
    CLARIFICATION_TRIAGE_STATUS,
    PIPELINE_RESULT_TO_EVAL_OUTCOME,
    EvalOutcome,
)


def eval_outcome_from_triage(ai_triage: dict[str, Any] | None) -> EvalOutcome | None:
    """Return the eval outcome for a ticket's `ai_triage`, or None if the run did not finish."""
    triage = ai_triage or {}
    if triage.get("status") == CLARIFICATION_TRIAGE_STATUS:
        return "needs_clarification"
    result = triage.get("result")
    if not isinstance(result, str) or not result:
        return None
    return PIPELINE_RESULT_TO_EVAL_OUTCOME.get(result)
