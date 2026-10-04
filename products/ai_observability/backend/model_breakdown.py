"""Shared definition of the model breakdown used by the AI observability dashboard tiles."""

from typing import Any

# The SDKs write `$ai_model` through untouched, so one model reaches us under several
# spellings once a project adds a gateway or a second provider: `gpt-5` and `openai/gpt-5`,
# `gemini-3-flash` and `models/gemini-3-flash`, `GLM-5.3` and `glm-5.3`. Event properties
# cannot be rewritten after ingestion, so a breakdown on the raw value shows one model as
# several bars forever. Fold the provider prefix and the case at query time instead.
NORMALIZED_MODEL_BREAKDOWN_HOGQL = "lower(replaceRegexpOne(toString(properties.$ai_model), '^.*/', ''))"

MODEL_BREAKDOWN_DESCRIPTION = (
    "Model names are folded to lowercase without the provider prefix, so openai/gpt-5 and gpt-5 count as one model."
)

# The shape the template wrote before the folding, kept so the backfill command can tell a
# tile that still carries the template's query from one a user has edited.
RAW_MODEL_BREAKDOWN_FILTER: dict[str, Any] = {"breakdown_type": "event", "breakdown": "$ai_model"}


def normalized_model_breakdown_filter() -> dict[str, Any]:
    return {"breakdown_type": "hogql", "breakdown": NORMALIZED_MODEL_BREAKDOWN_HOGQL}
