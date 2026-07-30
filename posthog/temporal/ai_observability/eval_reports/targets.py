"""Evaluation-target helpers shared by report queries and activities."""

GENERATION_TARGET = "generation"
TRACE_TARGET = "trace"
SESSION_TARGET = "session"

_AGGREGATE_TARGET_ID_SPACES = {TRACE_TARGET: "trace_id", SESSION_TARGET: "session_id"}


def resolve_evaluation_target(target: str | None) -> str:
    normalized_target = target or GENERATION_TARGET
    if normalized_target not in (GENERATION_TARGET, TRACE_TARGET, SESSION_TARGET):
        raise ValueError(f"Unsupported evaluation target: {normalized_target}")
    return normalized_target


def target_event_predicate(target: str | None) -> str:
    """Return a fixed SQL predicate for the evaluation event's target ID space."""
    id_space = _AGGREGATE_TARGET_ID_SPACES.get(resolve_evaluation_target(target))
    if id_space is not None:
        return f"properties.$ai_target_type = '{id_space}'"
    return "(properties.$ai_target_type = 'generation_uuid' OR isNull(properties.$ai_target_type))"
