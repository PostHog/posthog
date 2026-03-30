"""Helpers for emitting SLO lifecycle events around normal Python code.

Intended usage patterns:

1. Standard block instrumentation:

    with slo_operation(spec=spec, properties=props):
        do_work()

2. Explicit completion enrichment in the same block:

    with slo_operation(spec=spec) as slo:
        do_work()
        slo.tag(rows_processed=10)

3. Deep-call-stack enrichment without threading the handle through every call:

    def helper() -> None:
        tag_current_slo(cache_hit=True)
"""

import traceback
import dataclasses
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from os import sep
from pathlib import Path
from time import monotonic
from typing import Any

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
SLO_REPO_ROOT = Path(__file__).resolve().parents[2]
SLO_REPO_ROOT_STR = str(SLO_REPO_ROOT)
SLO_REPO_ROOT_PREFIX = f"{SLO_REPO_ROOT_STR}{sep}"


@dataclasses.dataclass(frozen=True)
class SloSpec:
    distinct_id: str
    area: SloArea
    operation: SloOperation
    team_id: int
    resource_id: str | None = None


@dataclasses.dataclass
class SloHandle:
    completion_properties: dict[str, JsonValue] = dataclasses.field(default_factory=dict)
    outcome_override: SloOutcome | None = None

    def tag(self, **props: JsonValue) -> None:
        for key, value in props.items():
            if value is None:
                self.completion_properties.pop(key, None)
            else:
                self.completion_properties[key] = value

    def succeed(self, **props: JsonValue) -> None:
        self.outcome_override = SloOutcome.SUCCESS
        self.tag(**props)

    def fail(self, **props: JsonValue) -> None:
        self.outcome_override = SloOutcome.FAILURE
        self.tag(**props)


_current_slo: ContextVar[SloHandle | None] = ContextVar("current_slo", default=None)


def get_current_slo() -> SloHandle | None:
    return _current_slo.get()


def tag_current_slo(**props: JsonValue) -> bool:
    slo = get_current_slo()
    if slo is None:
        return False

    slo.tag(**props)
    return True


def _is_repo_frame(filename: str) -> bool:
    normalized_filename = str(Path(filename).absolute())
    return normalized_filename == SLO_REPO_ROOT_STR or normalized_filename.startswith(SLO_REPO_ROOT_PREFIX)


def _build_error_origin(exc: Exception) -> str | None:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None

    origin = next((frame for frame in reversed(frames) if _is_repo_frame(frame.filename)), frames[-1])
    return f"{origin.filename}:{origin.lineno} in {origin.name}"


@contextmanager
def slo_operation(
    *,
    spec: SloSpec,
    properties: Mapping[str, JsonValue] | None = None,
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
    token = _current_slo.set(handle)

    try:
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
            handle.completion_properties.setdefault("error_origin", _build_error_origin(exc))
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
    finally:
        _current_slo.reset(token)
