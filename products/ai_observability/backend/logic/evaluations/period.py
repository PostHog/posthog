from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal

from posthog.dataclasses import frozen

Interval = Literal["hour", "day"]

# A period this short or shorter is bucketed by hour, so a day or two still draws a line rather than one or two dots.
MAX_HOURLY_SPAN = timedelta(days=2)


@frozen
class OverviewPeriod:
    start: datetime
    end: datetime
    previous_start: datetime
    # Before `start` when the current period is still running, so both periods cover the same length of time.
    previous_end: datetime
    interval: Interval
    # The start of each bucket in the project's timezone. The first one can start before `start`.
    buckets: tuple[datetime, ...]


def resolve_bound(value: date | datetime, tz: tzinfo, *, is_end: bool) -> datetime:
    """A date is a whole day in the project's timezone, so as an end it means the following midnight."""
    if isinstance(value, datetime):
        return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
    return datetime.combine(value + timedelta(days=1) if is_end else value, time.min, tz)


def overview_period(start: datetime, end: datetime, now: datetime, tz: tzinfo) -> OverviewPeriod:
    # Two datetimes that share a tzinfo subtract and compare by wall time, so a daylight saving change would alter
    # the period's length. UTC keeps every length and comparison in real time.
    start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
    duration = end_utc - start_utc
    previous_start = start_utc - duration
    interval: Interval = "hour" if duration <= MAX_HOURLY_SPAN else "day"
    return OverviewPeriod(
        start=start,
        end=end,
        previous_start=previous_start.astimezone(tz),
        previous_end=max(min(end_utc, now) - duration, previous_start).astimezone(tz),
        interval=interval,
        buckets=_buckets(start.astimezone(tz), end_utc, interval, tz),
    )


def _buckets(start: datetime, end: datetime, interval: Interval, tz: tzinfo) -> tuple[datetime, ...]:
    """`end` is in UTC, so each comparison with a local bucket is by instant."""
    buckets: list[datetime] = []
    if interval == "day":
        # Midnight by local date, because a day is 23 or 25 hours long across a daylight saving change.
        day = start.date()
        while (bucket := datetime.combine(day, time.min, tz)) < end:
            buckets.append(bucket)
            day += timedelta(days=1)
        return tuple(buckets)
    # Stepping in UTC keeps each step one real hour across a daylight saving change.
    bucket = start.replace(minute=0, second=0, microsecond=0)
    while bucket < end:
        buckets.append(bucket)
        bucket = (bucket.astimezone(UTC) + timedelta(hours=1)).astimezone(tz)
    return tuple(buckets)
