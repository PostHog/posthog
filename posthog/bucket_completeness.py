"""Which trailing buckets of a time series had not finished collecting.

A trend's final bucket is almost always partial — a daily insight refreshed at noon shows half of
today against full previous days — and ranges whose end rounds up to end-of-day add entirely future
buckets after it. Anything that compares those against complete buckets reports a collapse.

Callers supply their own reference time because the difference is real: an interactive tool asks
about `now`, while something reading a stored snapshot must ask about when the query actually ran.

All datetimes here are naive wall clock in one timezone. Converting an aware timestamp into the
team's wall clock once, in the caller, keeps DST out of the arithmetic: a spring-forward day is
still one calendar day wide when both sides are wall clock.
"""

from datetime import datetime, timedelta
from typing import Any, Union

from dateutil.relativedelta import relativedelta

# Trends emits bucket starts via TrendsQueryRunner.build_series_response; sub-day intervals carry a
# time, coarser ones do not.
_BUCKET_START_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# Appended to a bucket's date cell when that bucket is still collecting data.
PARTIAL_BUCKET_MARKER = " (partial)"

Period = Union[timedelta, relativedelta]


def parse_bucket_start(label: Any) -> datetime | None:
    """Parse a bucket label into naive project-local time, or None if it isn't one.

    Stickiness puts integer day-counts in `days` rather than dates, so non-strings are rejected
    rather than coerced.
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


def bucket_starts(days: Any) -> list[datetime] | None:
    """Parse a whole `days` list, all or nothing.

    A partly unparseable list would yield neighbours that are not really adjacent, so completeness
    is better left undecided than decided on a guess.
    """
    if not isinstance(days, list) or not days:
        return None
    starts = [start for start in (parse_bucket_start(day) for day in days) if start is not None]
    return starts if len(starts) == len(days) else None


def incomplete_from_index(
    starts: list[datetime] | None, *, reference: datetime | None, period: Period | None
) -> int | None:
    """Index of the first bucket that had not finished at `reference`, or None if all had.

    Returns None rather than guessing whenever completeness can't be established: no reference, no
    period, no buckets, or every bucket looking incomplete — which means the timestamps disagree
    with each other rather than that the data is missing, and trimming everything would leave
    nothing to describe.
    """
    if not starts or reference is None or period is None:
        return None

    # Every end but the last is the next bucket's start. Only the last is extrapolated, and it steps
    # by the named period: a calendar month is not as long as the one before it.
    ends = [*starts[1:], starts[-1] + period]

    incomplete = 0
    for end in reversed(ends):
        if end <= reference:
            break
        incomplete += 1

    if incomplete == 0 or incomplete == len(ends):
        return None
    return len(starts) - incomplete


def partial_bucket_flags(days: list[str], current_interval_start: datetime) -> list[bool]:
    """Flag each bucket that falls in the current (still-collecting) interval or later."""
    return [(start := parse_bucket_start(day)) is not None and start >= current_interval_start for day in days]


def partial_bucket_note(timezone: str) -> str:
    return (
        f'Note: rows marked "{PARTIAL_BUCKET_MARKER.strip()}" cover an interval that is still in progress '
        f"as of the query time, so their values are incomplete. Timezone: {timezone}."
    )
