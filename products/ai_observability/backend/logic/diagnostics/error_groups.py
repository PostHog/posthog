from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from ...facade.diagnostics_contracts import ErrorOrder
from .trends import Trend

DEFAULT_ERROR_ORDER: Final = ErrorOrder.OCCURRENCES


class ErrorView(LabeledStrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    NEW = "new"


@frozen
class ErrorGroupRow:
    """One normalized error message over the selection's range. `previous_occurrences` is None when the range has no
    previous window, and `series` counts the occurrences in each of the range's bucket starts."""

    message: str
    occurrences: int
    previous_occurrences: int | None
    traces: int
    users: int
    models: tuple[str, ...]
    last_seen: datetime
    trend: Trend
    series: tuple[int, ...]


@frozen
class ErrorCountsRow:
    total: int
    increasing: int
    decreasing: int
    max_occurrences: int


def first_seen_in_range(first_seen: datetime | None, range_start: datetime) -> bool:
    """Whether an error is new to a range: it has an occurrence and none from the lookback start to `range_start`."""
    return first_seen is not None and first_seen >= range_start


def series_of(counts: Mapping[int, int], starts: Sequence[datetime]) -> tuple[int, ...]:
    """The count in each bucket, from counts keyed by each bucket's start in Unix seconds. A start with no count had no
    occurrence."""
    # Unix seconds name one instant in any zone, so the two buckets of the hour a clock goes back stay apart.
    return tuple(counts.get(int(start.timestamp()), 0) for start in starts)
