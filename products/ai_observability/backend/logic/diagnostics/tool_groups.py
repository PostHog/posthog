from datetime import datetime
from typing import Final

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from ...facade.contracts import TraceMetricChangeTone
from ...facade.diagnostics_contracts import ToolFailureState, ToolListItem, ToolOrder
from .entity_keys import encode_entity_key
from .trends import change_label

DEFAULT_TOOL_ORDER: Final = ToolOrder.CALLS


class ToolView(LabeledStrEnum):
    FAILING = "failing"


@frozen
class ToolGroupRow:
    """One called tool over the selection's range. `previous_calls` is None when the range has no previous window.
    `results` and `failures` count the tool's captured results and failed results in the range, `failure_rate` is
    None when it has no captured result, and `series` counts the calls in each of the range's bucket starts."""

    name: str
    calls: int
    previous_calls: int | None
    traces: int
    results: int
    failures: int
    failure_rate: float | None
    only_tool_calls: int
    last_seen: datetime
    is_failing: bool
    series: tuple[int, ...]


@frozen
class ToolCountsRow:
    total: int
    failing: int
    max_calls: int


def tool_item(row: ToolGroupRow) -> ToolListItem:
    # Without a captured result the failures are unknown, not zero.
    captured = row.failure_rate is not None
    return ToolListItem(
        key=encode_entity_key(row.name),
        name=row.name,
        calls=row.calls,
        change_label=change_label(row.calls, row.previous_calls),
        change_tone=TraceMetricChangeTone.NEUTRAL,
        traces=row.traces,
        failure_rate=row.failure_rate,
        failures=row.failures if captured else None,
        failure_state=ToolFailureState.CAPTURED if captured else ToolFailureState.NOT_CAPTURED,
        is_failing=row.is_failing,
        only_tool_share=_share(row.only_tool_calls, row.calls),
        last_seen=row.last_seen,
        series=list(row.series),
    )


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0
