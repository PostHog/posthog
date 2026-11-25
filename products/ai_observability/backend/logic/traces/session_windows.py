from datetime import UTC, datetime, time, timedelta
from typing import Final

from .events_fallback import FALLBACK_AFTER_HINT, FALLBACK_BEFORE_HINT, FallbackWindow
from .session_queries import SESSION_FACTS_MAX_TRACES
from .trace_paging import SelectionPage
from .trace_selection import ALL_TIME_LOOKBACK, TraceWindow, shift

# The traces one read of sessions from the shared events table covers in all, so a page of old sessions stays bounded.
SHARED_FACTS_MAX_TRACES: Final = 1000


def ai_events_read_start(now: datetime, retention_days: int) -> datetime:
    """The oldest moment from which `posthog.ai_events` still holds the team's rows: the start of the first day whose
    rows have not expired. A row expires at the start of the UTC day `retention_days` after its own."""
    first_day_held = now.astimezone(UTC).date() - timedelta(days=retention_days - 1)
    return datetime.combine(first_day_held, time.min, tzinfo=UTC)


def session_window(now: datetime, read_start: datetime, timestamp_hint: datetime | None) -> TraceWindow:
    """The window one session is read in, for its turns and its facts alike: the team's AI events retention up to now,
    reaching back to just before a timestamp hint older than that retention, and no further than the lookback of an
    all-time list."""
    if timestamp_hint is None or timestamp_hint >= read_start:
        return TraceWindow(start=read_start, end=now)
    return TraceWindow(start=max(timestamp_hint - FALLBACK_BEFORE_HINT, now - ALL_TIME_LOOKBACK), end=now)


def is_past_retention(window: TraceWindow, read_start: datetime) -> bool:
    """Whether the window starts before `posthog.ai_events` may hold the team's rows, so only the shared events table
    holds all of it."""
    return window.start < read_start


def _shifted(moment: datetime, delta: timedelta) -> datetime | None:
    try:
        return shift(moment, delta)
    except OverflowError:
        return None


def listed_sessions_fallback(list_window: TraceWindow) -> FallbackWindow:
    """Where the facts of a listed session no longer in `posthog.ai_events` are read: the list's range, reaching back as
    far before it as a trace link's fallback reaches after its hint, so a session that started before the range keeps
    its earlier turns. It starts no earlier than the lookback of an all-time list."""
    read = list_window.read_bounds()
    starts = [
        start for start in (_shifted(read.start, -FALLBACK_AFTER_HINT), _shifted(read.end, -ALL_TIME_LOOKBACK)) if start
    ]
    return FallbackWindow(start=max(starts, default=read.start), end=read.end)


def shared_facts_traces_per_session(session_count: int) -> int:
    """How many of each session's most recent traces a read from the shared events table covers: an equal share of
    `SHARED_FACTS_MAX_TRACES`, at least one, and at most what a read from `posthog.ai_events` covers."""
    return max(1, min(SESSION_FACTS_MAX_TRACES, SHARED_FACTS_MAX_TRACES // max(session_count, 1)))


def is_unknown_session(page: SelectionPage, *, read_from_start: bool) -> bool:
    """A session whose turns read from its start find none holds no traces in the window."""
    return read_from_start and not page.positions
