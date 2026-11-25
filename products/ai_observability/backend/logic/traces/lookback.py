from datetime import datetime, timedelta
from typing import Final

from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow, shift

LOOKBACK: Final[timedelta] = timedelta(days=30)


def lookback_window(window: TraceWindow) -> TraceWindow:
    return TraceWindow(start=shift(window.start, -LOOKBACK), end=window.start)


def unscoped_selection(selection: TraceSelection, window: TraceWindow) -> TraceSelection:
    """Every trace in the window under the selection's test-account switch and support rule, without its filters,
    search or scopes. A read that describes a person rather than picking them reads this, so a filter never hides their
    activity."""
    return TraceSelection(
        window=window,
        filter_test_accounts=selection.filter_test_accounts,
        include_support_traces=selection.include_support_traces,
    )


def lookback_selection(selection: TraceSelection) -> TraceSelection:
    return unscoped_selection(selection, lookback_window(selection.window))


def seen_before(window: TraceWindow) -> datetime:
    return lookback_window(window).start


def has_no_lookback(window: TraceWindow) -> bool:
    """Whether the lookback, with its read buffer, would start before the first representable date, as for a window
    starting in the first month of year 1."""
    try:
        lookback_window(window).read_bounds()
    except OverflowError:
        return True
    return False
