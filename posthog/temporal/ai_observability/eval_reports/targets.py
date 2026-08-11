"""Evaluation-target descriptors shared by report queries, tools, and prompts.

One entry per target, so adding a target is adding a row here rather than another
`if target == ...` branch in every consumer.
"""

from dataclasses import dataclass

GENERATION_TARGET = "generation"
TRACE_TARGET = "trace"
SESSION_TARGET = "session"

TRACE_ID_ALLOWLIST_KEY = "trace_id_allowlist"
SESSION_ID_ALLOWLIST_KEY = "session_id_allowlist"


@dataclass(frozen=True, kw_only=True)
class EvaluationTargetDescriptor:
    """Everything the report pipeline needs to know about one evaluation target.

    `event_id_space` is the `$ai_target_type` the evaluation emitter writes. Generation
    predates the property, so its events carry `generation_uuid` or nothing at all.

    `allowlist_key` names the agent-state list of IDs this target's evaluation queries
    returned. Detail tools refuse IDs that aren't on it, so the agent can only inspect
    units its own report period actually surfaced.
    """

    name: str
    unit_label: str
    id_key: str
    event_id_space: str | None
    allowlist_key: str | None


_DESCRIPTORS: dict[str, EvaluationTargetDescriptor] = {
    GENERATION_TARGET: EvaluationTargetDescriptor(
        name=GENERATION_TARGET,
        unit_label="generation",
        id_key="generation_id",
        event_id_space=None,
        allowlist_key=None,
    ),
    TRACE_TARGET: EvaluationTargetDescriptor(
        name=TRACE_TARGET,
        unit_label="trace",
        id_key="trace_id",
        event_id_space="trace_id",
        allowlist_key=TRACE_ID_ALLOWLIST_KEY,
    ),
    SESSION_TARGET: EvaluationTargetDescriptor(
        name=SESSION_TARGET,
        unit_label="session",
        id_key="session_id",
        event_id_space="session_id",
        allowlist_key=SESSION_ID_ALLOWLIST_KEY,
    ),
}

EVALUATION_TARGETS: tuple[str, ...] = tuple(_DESCRIPTORS)


def resolve_evaluation_target(target: str | None) -> str:
    normalized_target = target or GENERATION_TARGET
    if normalized_target not in _DESCRIPTORS:
        raise ValueError(f"Unsupported evaluation target: {normalized_target}")
    return normalized_target


def get_target_descriptor(target: str | None) -> EvaluationTargetDescriptor:
    return _DESCRIPTORS[resolve_evaluation_target(target)]


def target_event_predicate(target: str | None) -> str:
    """Return a fixed SQL predicate for the evaluation event's target ID space."""
    id_space = get_target_descriptor(target).event_id_space
    if id_space is not None:
        return f"properties.$ai_target_type = '{id_space}'"
    return "(properties.$ai_target_type = 'generation_uuid' OR isNull(properties.$ai_target_type))"
