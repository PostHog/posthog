from datetime import UTC, datetime, timedelta, timezone

import pytest

from products.ai_observability.backend.logic.traces.events_fallback import FALLBACK_AFTER_HINT, FALLBACK_BEFORE_HINT
from products.ai_observability.backend.logic.traces.session_queries import SESSION_FACTS_MAX_TRACES
from products.ai_observability.backend.logic.traces.session_windows import (
    SHARED_FACTS_MAX_TRACES,
    ai_events_read_start,
    is_past_retention,
    listed_sessions_fallback,
    session_window,
    shared_facts_traces_per_session,
)
from products.ai_observability.backend.logic.traces.trace_selection import (
    ALL_TIME_LOOKBACK,
    CAPTURE_BUFFER,
    TraceWindow,
)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
RETENTION_START = NOW - timedelta(days=60)
OLD_HINT = RETENTION_START - timedelta(days=20)


@pytest.mark.parametrize(
    "hint, expected, past_retention",
    [
        (None, TraceWindow(start=RETENTION_START, end=NOW), False),
        (RETENTION_START, TraceWindow(start=RETENTION_START, end=NOW), False),
        (OLD_HINT, TraceWindow(start=OLD_HINT - FALLBACK_BEFORE_HINT, end=NOW), True),
        (
            NOW - ALL_TIME_LOOKBACK - timedelta(days=900),
            TraceWindow(start=NOW - ALL_TIME_LOOKBACK, end=NOW),
            True,
        ),
    ],
    ids=["no hint", "hint inside the retention", "hint older than the retention", "hint older than the lookback"],
)
def test_a_session_reads_up_to_now_from_the_retention_or_an_older_hint(
    hint: datetime | None, expected: TraceWindow, past_retention: bool
) -> None:
    window = session_window(NOW, RETENTION_START, hint)

    assert (window, is_past_retention(window, RETENTION_START)) == (expected, past_retention)


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 11, 24, 12, 0, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC)),
        (datetime(2026, 11, 24, 0, 0, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC)),
        (datetime(2026, 11, 24, 1, 0, tzinfo=timezone(timedelta(hours=2))), datetime(2026, 10, 25, tzinfo=UTC)),
    ],
    ids=["midday", "midnight", "a zone ahead of UTC"],
)
def test_ai_events_are_read_from_the_first_day_whose_rows_have_not_expired(now: datetime, expected: datetime) -> None:
    assert ai_events_read_start(now, retention_days=30) == expected


@pytest.mark.parametrize(
    "start, end, expected_start",
    [
        (NOW - timedelta(days=1), NOW, NOW - timedelta(days=1) - CAPTURE_BUFFER - FALLBACK_AFTER_HINT),
        (datetime(1900, 1, 1, tzinfo=UTC), NOW, NOW + CAPTURE_BUFFER - ALL_TIME_LOOKBACK),
        (datetime(1, 1, 3, tzinfo=UTC), datetime(1, 1, 4, tzinfo=UTC), datetime(1, 1, 3, tzinfo=UTC) - CAPTURE_BUFFER),
    ],
    ids=["a week before the range", "no earlier than an all-time list", "at the edge of the datetime range"],
)
def test_listed_sessions_fall_back_a_week_before_the_range_within_the_all_time_lookback(
    start: datetime, end: datetime, expected_start: datetime
) -> None:
    fallback = listed_sessions_fallback(TraceWindow(start=start, end=end))

    assert (fallback.start, fallback.end) == (expected_start, end + CAPTURE_BUFFER)


@pytest.mark.parametrize(
    "session_count, expected",
    [
        (1, SESSION_FACTS_MAX_TRACES),
        (100, SHARED_FACTS_MAX_TRACES // 100),
        (SHARED_FACTS_MAX_TRACES * 2, 1),
    ],
    ids=["one session", "a full page", "more sessions than traces"],
)
def test_sessions_read_from_the_shared_events_table_share_one_trace_budget(session_count: int, expected: int) -> None:
    assert shared_facts_traces_per_session(session_count) == expected
