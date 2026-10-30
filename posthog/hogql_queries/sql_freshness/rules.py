from collections.abc import Callable
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
    SqlWindowClass.FIXED_PAST: timedelta(hours=24),
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


@frozen
class Cap:
    until: datetime
    reason: FreshnessReason
    window: Optional[SqlWindowClass] = None


Verdict = Optional[Reject | Cap]
Rule = Callable[[QueryFacts], Verdict]


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


def _reads_fixed_past(facts: QueryFacts) -> bool:
    return any(window_class(window, facts) == SqlWindowClass.FIXED_PAST for window in facts.windows)


def supported_fields_only(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.UNSUPPORTED_FIELD) if facts.unsupported_field else None


def no_joins(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.JOIN) if facts.join else None


def only_events_sources(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.FOREIGN_SOURCE) if facts.foreign_source else None


def supported_bounds(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.UNSUPPORTED_BOUND) if facts.unsupported_bound else None


def every_select_bounded(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.UNBOUNDED) if facts.unbounded_select or not facts.windows else None


def no_clock_outside_bounds(facts: QueryFacts) -> Verdict:
    return Reject(reason=FreshnessReason.CLOCK_OUTSIDE_BOUNDS) if facts.clock_outside_bounds else None


def window_age(facts: QueryFacts) -> Verdict:
    if not facts.windows:
        return None
    window = min((window_class(window, facts) for window in facts.windows), key=SQL_WINDOW_MAX_AGE.__getitem__)
    return Cap(until=facts.now + SQL_WINDOW_MAX_AGE[window], reason=FreshnessReason.WINDOW_AGE, window=window)


def clock_days_end_at_midnight(facts: QueryFacts) -> Verdict:
    if not (facts.reads_clock or facts.relative_date_range):
        return None
    next_midnight = min(facts.start_of_today + timedelta(days=1), facts.start_of_utc_today + timedelta(days=1))
    return Cap(until=next_midnight, reason=FreshnessReason.CLOCK_DAY)


def now_anchored_past_moves(facts: QueryFacts) -> Verdict:
    if not (facts.reads_now or facts.rolling_filters) or not _reads_fixed_past(facts):
        return None
    return Cap(until=facts.now + SQL_WINDOW_MAX_AGE[SqlWindowClass.UP_TO_NOW_LONG], reason=FreshnessReason.NOW_ANCHORED)


RULES: tuple[Rule, ...] = (
    supported_fields_only,
    no_joins,
    only_events_sources,
    supported_bounds,
    every_select_bounded,
    no_clock_outside_bounds,
    window_age,
    clock_days_end_at_midnight,
    now_anchored_past_moves,
)
