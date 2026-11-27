from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.facade.contracts import TraceMetricChangeTone
from products.ai_observability.backend.facade.diagnostics_contracts import ToolFailureState
from products.ai_observability.backend.logic.diagnostics.entity_keys import encode_entity_key
from products.ai_observability.backend.logic.diagnostics.tool_groups import ToolGroupRow, tool_item, trace_share


def _row(**overrides: Any) -> ToolGroupRow:
    return ToolGroupRow(
        **{
            "name": "run_query",
            "calls": 8,
            "previous_calls": 4,
            "traces": 5,
            "results": 20,
            "failures": 2,
            "failure_rate": 0.1,
            "only_tool_calls": 6,
            "last_seen": datetime(2026, 9, 1, 10, tzinfo=UTC),
            "is_failing": True,
            "series": (3, 5),
            **overrides,
        }
    )


@parameterized.expand(
    [
        ("captured", _row(), 0.1, 2, ToolFailureState.CAPTURED),
        (
            "not_captured_keeps_failures_unknown",
            _row(results=0, failures=0, failure_rate=None, is_failing=False),
            None,
            None,
            ToolFailureState.NOT_CAPTURED,
        ),
    ]
)
def test_tool_item_failures(
    _name: str, row: ToolGroupRow, rate: float | None, failures: int | None, state: ToolFailureState
) -> None:
    item = tool_item(row)

    assert (item.failure_rate, item.failures, item.failure_state) == (rate, failures, state)


def test_tool_item_share_tone_and_key() -> None:
    item = tool_item(_row())

    assert (item.key, item.change_label, item.change_tone, item.only_tool_share) == (
        encode_entity_key("run_query"),
        "+100%",
        TraceMetricChangeTone.NEUTRAL,
        0.75,
    )


@parameterized.expand(
    [
        ("some_traces", 5, 20, 0.25),
        ("a_range_with_no_trace", 0, 0, 0.0),
        ("a_count_past_a_stale_total", 103, 100, 1.0),
    ]
)
def test_trace_share(_name: str, traces: int, total_traces: int, expected: float) -> None:
    assert trace_share(traces, total_traces) == expected
