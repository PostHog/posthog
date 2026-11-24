"""The date range a set-level read counts checks over.

The overview, the rankings, the citations list, the keyword reports and the needs-improvement filter all
take `date_from` and `date_to` the way the web analytics queries do, so the parsing and the limits live here.
"""

from __future__ import annotations

import re
import datetime as dt
from zoneinfo import ZoneInfo

from dateutil import parser

from posthog.dataclasses import frozen
from posthog.utils import relative_date_parse

from products.aeo.backend.facade.contracts import DEFAULT_DATE_FROM, MAX_WINDOW_DAYS, InvalidDateRangeError

# `relative_date_parse` reads any text it cannot parse as "now", so the format is checked first.
# Hours are left out because the checks run once a day.
_RELATIVE_DAY = re.compile(r"-?[0-9]*[dwmqyDWMQY](Start|End)?")
_FORMAT_HELP = "Use a date such as 2026-11-01 or a relative day such as -30d."


@frozen
class CheckWindow:
    """Whole days in the team's timezone. `start` is inclusive and `until` is exclusive."""

    window_from: dt.date
    window_to: dt.date
    start: dt.datetime
    until: dt.datetime
    # Start of the window of the same length that ends where this one starts.
    previous_start: dt.datetime

    @property
    def days(self) -> int:
        return (self.window_to - self.window_from).days + 1


def resolve_window(
    date_from: str | None,
    date_to: str | None,
    *,
    timezone_name: str,
    now: dt.datetime,
    default_date_from: str = DEFAULT_DATE_FROM,
) -> CheckWindow:
    """The window from `date_from` to `date_to`, both inclusive. A missing `date_to` is today, and a
    `date_to` in the future is read as today. Raises InvalidDateRangeError."""
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    window_from = _parse_day(date_from or default_date_from, tz, now, field="date_from")
    window_to = min(_parse_day(date_to, tz, now, field="date_to"), today) if date_to else today
    if window_from > window_to:
        raise InvalidDateRangeError("date_from", "date_from must not be after date_to or after today.")
    days = (window_to - window_from).days + 1
    if days > MAX_WINDOW_DAYS:
        raise InvalidDateRangeError("date_from", f"The date range can cover at most {MAX_WINDOW_DAYS} days.")
    start = dt.datetime.combine(window_from, dt.time.min, tzinfo=tz)
    day_after = dt.datetime.combine(window_to + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
    return CheckWindow(
        window_from=window_from,
        window_to=window_to,
        start=start,
        # Every read of one request stops at the same instant, so a check written mid-request
        # cannot make two counts disagree.
        until=min(day_after, now),
        previous_start=dt.datetime.combine(window_from - dt.timedelta(days=days), dt.time.min, tzinfo=tz),
    )


def _parse_day(value: str, tz: ZoneInfo, now: dt.datetime, *, field: str) -> dt.date:
    value = value.strip()
    if not _RELATIVE_DAY.fullmatch(value):
        try:
            parser.isoparse(value)
        except ValueError:
            raise InvalidDateRangeError(field, f"'{value}' is not a valid {field}. {_FORMAT_HELP}")
    return relative_date_parse(value, tz, now=now).date()
