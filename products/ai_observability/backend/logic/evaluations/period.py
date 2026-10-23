from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal

from posthog.dataclasses import frozen

Interval = Literal["hour", "day"]

# A period this short or shorter is bucketed by hour, so a day or two still draws a line rather than one or two dots.
MAX_HOURLY_SPAN = timedelta(days=2)
DEFAULT_DAYS = 14
MAX_DAYS = 90


def _resolve_bound(value: date | datetime, tz: tzinfo, *, is_end: bool) -> datetime:
    """A date is a whole day in the project's timezone, so as an end it means the following midnight."""
    if isinstance(value, datetime):
        return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
    return datetime.combine(value + timedelta(days=1) if is_end else value, time.min, tz)


class InvalidPeriodError(ValueError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        # The request parameter at fault, or None when the period as a whole is out of range.
        self.field = field


@frozen
class PeriodBounds:
    start: datetime
    end: datetime  # Exclusive.

    @classmethod
    def from_request(
        cls, date_from: date | datetime | None, date_to: date | datetime | None, tz: tzinfo
    ) -> "PeriodBounds":
        """A date is a whole day in the project's timezone, a datetime is an exact instant. Without bounds, the period
        is the last 14 days up to and including today."""
        try:
            date_to = date_to or datetime.now(tz).date()
            if date_from is None:
                date_from = (
                    date_to - timedelta(days=DEFAULT_DAYS)
                    if isinstance(date_to, datetime)
                    else date_to - timedelta(days=DEFAULT_DAYS - 1)
                )
            end = _resolve_bound(date_to, tz, is_end=True)
            start = _resolve_bound(date_from, tz, is_end=False)
            # Both bounds share the project's tzinfo, which compares wall time, so this compares instants instead.
            length = end.astimezone(UTC) - start.astimezone(UTC)
            # The overview also reads the period of equal length before this one, so its start must exist too.
            start.astimezone(UTC) - length
        except OverflowError as error:
            raise InvalidPeriodError("The period is outside the supported date range.") from error
        if length <= timedelta(0):
            raise InvalidPeriodError("Must be before date_to.", field="date_from")
        # Whole days count by the calendar, because a day across a daylight saving change is 23 or 25 hours long.
        # An instant has no such change, so a period with one counts real time.
        if not isinstance(date_from, datetime) and not isinstance(date_to, datetime):
            too_long = (date_to - date_from).days + 1 > MAX_DAYS
        else:
            too_long = length > timedelta(days=MAX_DAYS)
        if too_long:
            raise InvalidPeriodError(f"The period can cover at most {MAX_DAYS} days.", field="date_from")
        return cls(start=start, end=end)


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
