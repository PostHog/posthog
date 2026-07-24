"""Evaluation-target helpers shared by report queries and activities."""

GENERATION_TARGET = "generation"
TRACE_TARGET = "trace"


def resolve_evaluation_target(target: str | None) -> str:
    normalized_target = target or GENERATION_TARGET
    if normalized_target not in (GENERATION_TARGET, TRACE_TARGET):
        raise ValueError(f"Unsupported evaluation target: {normalized_target}")
    return normalized_target


def target_event_predicate(target: str | None) -> str:
    """Return a fixed SQL predicate for the evaluation event's target ID space."""
    if resolve_evaluation_target(target) == TRACE_TARGET:
        return "properties.$ai_target_type = 'trace_id'"
    return "(properties.$ai_target_type = 'generation_uuid' OR isNull(properties.$ai_target_type))"
