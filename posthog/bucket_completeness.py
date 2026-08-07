"""Which trailing buckets of a time series had not finished collecting.

All datetimes here are naive wall clock in one timezone. Converting an aware timestamp once, in the
caller, keeps DST out of the arithmetic: a spring-forward day is still one calendar day wide.
"""

from datetime import datetime, timedelta
from typing import Union

from dateutil.relativedelta import relativedelta

# Shapes emitted by TrendsQueryRunner.build_series_response.
_BUCKET_START_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

Period = Union[timedelta, relativedelta]


def parse_bucket_start(label: object) -> datetime | None:
    """Parse a bucket label into naive project-local time, or None if it isn't one.

    Stickiness puts integer day-counts in `days` rather than dates, so non-strings are rejected.
    """
    if not isinstance(label, str):
        return None
    for fmt in _BUCKET_START_FORMATS:
        try:
            return datetime.strptime(label, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(label).replace(tzinfo=None)
    except ValueError:
        return None


def bucket_starts(days: object) -> list[datetime] | None:
    """Parse a whole `days` list, all or nothing.

    A partly unparseable list would yield neighbours that are not really adjacent.
    """
    if not isinstance(days, list) or not days:
        return None
    starts = [start for start in (parse_bucket_start(day) for day in days) if start is not None]
    return starts if len(starts) == len(days) else None


def incomplete_from_index(
    starts: list[datetime] | None, *, reference: datetime | None, period: Period | None
) -> int | None:
    """Index of the first bucket that had not finished at `reference`, or None if all had."""
    if not starts or reference is None or period is None:
        return None

    # Only the last end is extrapolated, and by the named period — calendar months differ in length.
    ends = [*starts[1:], starts[-1] + period]

    incomplete = 0
    for end in reversed(ends):
        if end <= reference:
            break
        incomplete += 1

    if incomplete == 0:
        return None
    return len(starts) - incomplete
