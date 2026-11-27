from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum

from products.ai_observability.backend.logic.traces.trace_metrics import ChangeTone

INCREASE_MIN_PERCENT = 20
DECREASE_MIN_PERCENT = 20
TREND_MIN_OCCURRENCES = 10
FAILING_MIN_RATE = 0.05
FAILING_MIN_RESULTS = 20

MINUS_SIGN = "−"


class Trend(StrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STEADY = "steady"


def change_label(current: int, previous: int | None) -> str | None:
    if previous is None:
        return None
    if previous == 0:
        return "was 0" if current else "0%"
    # Truncating toward zero in integers keeps the label under a threshold whenever the trend is, as +19.5% reads
    # "+19%" and not "+20%" beside a steady trend.
    percent = abs(current - previous) * 100 // previous
    if percent == 0:
        return "0%"
    return f"+{percent}%" if current > previous else f"{MINUS_SIGN}{percent}%"


def paired_with_range(previous_series: Sequence[int], bucket_count: int) -> tuple[int, ...]:
    """The previous period's series cut or padded with zeros at its end to the range's `bucket_count`, so its bucket i
    pairs with the range's bucket i. A range with no previous period keeps its empty series."""
    # The two periods have the same length, but the range's bounds can fall at other times of day than the previous
    # period's, which gives one of them a bucket more.
    if not previous_series:
        return ()
    return tuple(previous_series[:bucket_count]) + (0,) * (bucket_count - len(previous_series))


def error_change_tone(trend: Trend) -> ChangeTone:
    match trend:
        case Trend.INCREASING:
            return ChangeTone.BAD
        case Trend.DECREASING:
            return ChangeTone.GOOD
        case Trend.STEADY:
            return ChangeTone.NEUTRAL


def series_of(counts: Mapping[int, int], starts: Sequence[datetime]) -> tuple[int, ...]:
    """The count in each bucket, from counts keyed by each bucket's start in Unix seconds. A start with no count had no
    occurrence."""
    # Unix seconds name one instant in any zone, so the two buckets of the hour a clock goes back stay apart.
    return tuple(counts.get(int(start.timestamp()), 0) for start in starts)
