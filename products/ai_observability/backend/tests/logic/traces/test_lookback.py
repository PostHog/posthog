from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from products.ai_observability.backend.logic.traces.lookback import (
    LOOKBACK,
    first_seen_selection,
    has_no_lookback,
    lookback_selection,
    lookback_window,
    seen_before,
    unscoped_selection,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceGroupScope, TraceSelection, TraceWindow

WINDOW = TraceWindow(start=datetime(2026, 11, 18, tzinfo=UTC), end=datetime(2026, 11, 25, tzinfo=UTC))


def test_lookback_window_ends_at_the_range_start_and_spans_thirty_days():
    assert lookback_window(WINDOW) == TraceWindow(
        start=datetime(2026, 10, 19, tzinfo=UTC), end=datetime(2026, 11, 18, tzinfo=UTC)
    )
    assert LOOKBACK == timedelta(days=30)


@pytest.mark.parametrize(
    "build, window",
    [
        pytest.param(lookback_selection, lookback_window(WINDOW), id="lookback"),
        pytest.param(
            first_seen_selection,
            TraceWindow(start=datetime(2026, 10, 19, tzinfo=UTC), end=WINDOW.end),
            id="first seen, from the lookback start to the range end",
        ),
        pytest.param(lambda selection: unscoped_selection(selection, WINDOW), WINDOW, id="the range itself"),
    ],
)
def test_person_reads_keep_only_the_test_account_and_support_switches(
    build: Callable[[TraceSelection], TraceSelection], window: TraceWindow
):
    selection = TraceSelection(
        window=WINDOW,
        properties=(EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT),),
        filter_test_accounts=True,
        include_support_traces=True,
        search="refund",
        person_id="person-1",
        error="Rate limit reached",
        tool="search_docs",
        failed_tool="run_query",
        group=TraceGroupScope(key="acme", type_index=0),
        quick_filter="errors",
    )

    assert build(selection) == TraceSelection(window=window, filter_test_accounts=True, include_support_traces=True)


def test_seen_before_is_the_lookback_start():
    assert seen_before(WINDOW) == datetime(2026, 10, 19, tzinfo=UTC)


@parameterized.expand(
    [
        ("a_recent_range", WINDOW, False),
        (
            "a_range_starting_inside_the_first_month",
            TraceWindow(start=datetime(1, 1, 20, tzinfo=UTC), end=WINDOW.end),
            True,
        ),
        (
            "a_lookback_starting_inside_the_read_buffer",
            TraceWindow(start=datetime(1, 1, 31, 0, 5, tzinfo=UTC), end=WINDOW.end),
            True,
        ),
    ]
)
def test_has_no_lookback_when_the_lookback_reads_before_the_first_date(
    _name: str, window: TraceWindow, expected: bool
) -> None:
    assert has_no_lookback(window) is expected
