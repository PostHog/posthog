from datetime import datetime, timedelta
from enum import StrEnum
from typing import Optional

from posthog.dataclasses import frozen
from posthog.hogql_queries.sql_freshness.facts import QueryFacts, Window


class SqlWindowClass(StrEnum):
    FIXED_PAST = "fixed_past"
    LIVE = "live"
    UP_TO_NOW_SHORT = "up_to_now_short"
    UP_TO_NOW_LONG = "up_to_now_long"


SQL_WINDOW_MAX_AGE: dict[SqlWindowClass, timedelta] = {
    SqlWindowClass.FIXED_PAST: timedelta(hours=6),
    SqlWindowClass.LIVE: timedelta(minutes=5),
    SqlWindowClass.UP_TO_NOW_SHORT: timedelta(minutes=30),
    SqlWindowClass.UP_TO_NOW_LONG: timedelta(hours=1),
}

LIVE_WINDOW_MAX_LENGTH = timedelta(hours=1)
SHORT_WINDOW_MAX_LENGTH = timedelta(days=1)
FIXED_PAST_SETTLE_TIME = timedelta(hours=1)


class FreshnessReason(StrEnum):
    WINDOW_AGE = "window_age"
    CLOCK_DAY = "clock_day"
    NOW_ANCHORED = "now_anchored"
    NO_EVENTS = "no_events"
    UNSUPPORTED_FIELD = "unsupported_field"
    JOIN = "join"
    FOREIGN_SOURCE = "foreign_source"
    UNBOUNDED = "unbounded"
    UNSUPPORTED_BOUND = "unsupported_bound"
    CLOCK_OUTSIDE_BOUNDS = "clock_outside_bounds"
    UNPARSEABLE = "unparseable"


@frozen
class Reject:
    reason: FreshnessReason


def window_class(window: Window, facts: QueryFacts) -> SqlWindowClass:
    if (
        window.end is not None
        and window.end <= facts.start_of_today
        and window.end <= facts.now - FIXED_PAST_SETTLE_TIME
    ):
        return SqlWindowClass.FIXED_PAST
    length = facts.now - window.start
    if length <= LIVE_WINDOW_MAX_LENGTH:
        return SqlWindowClass.LIVE
    if length <= SHORT_WINDOW_MAX_LENGTH:
        return SqlWindowClass.UP_TO_NOW_SHORT
    return SqlWindowClass.UP_TO_NOW_LONG


def shortest_lived_window(facts: QueryFacts) -> SqlWindowClass:
    return min((window_class(window, facts) for window in facts.windows), key=SQL_WINDOW_MAX_AGE.__getitem__)


def reject_reason(facts: QueryFacts) -> Optional[FreshnessReason]:
    checks = (
        (facts.unsupported_field, FreshnessReason.UNSUPPORTED_FIELD),
        (facts.join, FreshnessReason.JOIN),
        (facts.foreign_source, FreshnessReason.FOREIGN_SOURCE),
        (facts.unsupported_bound, FreshnessReason.UNSUPPORTED_BOUND),
        (facts.unbounded_select or not facts.windows, FreshnessReason.UNBOUNDED),
        (facts.clock_outside_bounds, FreshnessReason.CLOCK_OUTSIDE_BOUNDS),
    )
    return next((reason for failed, reason in checks if failed), None)


def fresh_until(facts: QueryFacts) -> tuple[datetime, FreshnessReason]:
    """Every limit that applies holds at once, so the earliest one sets the expiry."""
    limits = [(facts.now + SQL_WINDOW_MAX_AGE[shortest_lived_window(facts)], FreshnessReason.WINDOW_AGE)]
    if facts.reads_clock or facts.relative_inputs:
        next_midnight = min(facts.start_of_today, facts.start_of_utc_today) + timedelta(days=1)
        limits.append((next_midnight, FreshnessReason.CLOCK_DAY))
    reads_fixed_past = any(window_class(window, facts) == SqlWindowClass.FIXED_PAST for window in facts.windows)
    if (facts.reads_now or facts.relative_inputs) and reads_fixed_past:
        limits.append((facts.now + SQL_WINDOW_MAX_AGE[SqlWindowClass.UP_TO_NOW_LONG], FreshnessReason.NOW_ANCHORED))
    return min(limits, key=lambda limit: limit[0])
