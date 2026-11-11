from __future__ import annotations

import statistics
from collections.abc import Sequence

from posthog.temporal.health_checks.rollups.fill import DayFill
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.store import DayStats

MIN_FRACTION_OF_MEDIAN = 0.5
MIN_HISTORY_DAYS_FOR_MEDIAN = 3
D2_CHANGE_THRESHOLD = 0.01


def refusal_reason(rollup: type[DailyRollup], fill: DayFill, history: Sequence[DayStats], *, force: bool) -> str | None:
    """Why the filled day must not be published, or None when it may be.

    `force` lifts only the median floor. An empty day is always refused, because an empty day is what
    a ClickHouse outage looks like. `fill_day` refuses a day over the row cap before this runs.
    """
    if fill.row_count == 0:
        return "the day has no rows"
    if force or len(history) < MIN_HISTORY_DAYS_FOR_MEDIAN:
        return None
    median_rows = statistics.median(stats.row_count for stats in history)
    if fill.row_count < median_rows * MIN_FRACTION_OF_MEDIAN:
        return (
            f"the day has {fill.row_count:,} rows, under {MIN_FRACTION_OF_MEDIAN:.0%} of the "
            f"{len(history)}-day median of {median_rows:,.0f}"
        )
    return None


def _relative_change(published: int, filled: int) -> float:
    if published == 0:
        return 0.0 if filled == 0 else 1.0
    return abs(filled - published) / published


def day_moved(published: DayStats | None, fill: DayFill) -> bool:
    """Whether a refill differs enough from the published day to replace it."""
    if published is None:
        return True
    return (
        _relative_change(published.row_count, fill.row_count) > D2_CHANGE_THRESHOLD
        or _relative_change(published.event_count, fill.event_count) > D2_CHANGE_THRESHOLD
    )
