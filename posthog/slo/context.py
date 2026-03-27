import dataclasses
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from time import monotonic
from typing import Any

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties


@dataclasses.dataclass(frozen=True)
class SloSpec:
    distinct_id: str
    area: SloArea
    operation: SloOperation
    team_id: int
    resource_id: str | None = None


@dataclasses.dataclass
class SloHandle:
    completion_properties: dict[str, Any] = dataclasses.field(default_factory=dict)
    outcome_override: SloOutcome | None = None

    def tag(self, **props: Any) -> None:
        self.completion_properties.update({key: value for key, value in props.items() if value is not None})

    def succeed(self, **props: Any) -> None:
        self.outcome_override = SloOutcome.SUCCESS
        self.tag(**props)

    def fail(self, **props: Any) -> None:
        self.outcome_override = SloOutcome.FAILURE
        self.tag(**props)


@contextmanager
def slo_operation(
    *,
    spec: SloSpec,
    properties: Mapping[str, Any] | None = None,
    capture: Callable[..., Any] | None = None,
) -> Iterator[SloHandle]:
    """Emit SLO started/completed events around a block of normal Python code.

    ``properties`` are attached to both started and completed events.
    Use the yielded ``SloHandle`` to add completion-only properties or to mark
    a no-exception path as an SLO failure.
    """

    handle = SloHandle()
    base_properties = dict(properties or {})
    started_at = monotonic()

    emit_slo_started(
        distinct_id=spec.distinct_id,
        properties=SloStartedProperties(
            area=spec.area,
            operation=spec.operation,
            team_id=spec.team_id,
            resource_id=spec.resource_id,
        ),
        extra_properties=base_properties or None,
        capture=capture,
    )

    outcome = SloOutcome.SUCCESS
    try:
        yield handle
        outcome = handle.outcome_override or SloOutcome.SUCCESS
    except Exception as exc:
        handle.completion_properties.setdefault("error_type", type(exc).__name__)
        handle.completion_properties.setdefault("error_message", str(exc))
        outcome = SloOutcome.FAILURE
        raise
    finally:
        completion_properties = {**base_properties, **handle.completion_properties} or None
        emit_slo_completed(
            distinct_id=spec.distinct_id,
            properties=SloCompletedProperties(
                area=spec.area,
                operation=spec.operation,
                team_id=spec.team_id,
                outcome=outcome,
                resource_id=spec.resource_id,
                duration_ms=(monotonic() - started_at) * 1000,
            ),
            extra_properties=completion_properties,
            capture=capture,
        )
