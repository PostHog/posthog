from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from products.customer_analytics.backend.models import SlackSummaryCadence


def get_last_closed_period(cadence: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The most recent fully-elapsed calendar window for ``cadence`` in ``tz``.

    Daily → yesterday, weekly → last ISO week (Monday to Monday), monthly → last
    calendar month. Returns aware ``[start, end)`` datetimes at local midnight.
    """
    today = now.astimezone(tz).date()
    if cadence == SlackSummaryCadence.DAILY:
        start, end = today - timedelta(days=1), today
    elif cadence == SlackSummaryCadence.WEEKLY:
        this_monday = today - timedelta(days=today.weekday())
        start, end = this_monday - timedelta(days=7), this_monday
    elif cadence == SlackSummaryCadence.MONTHLY:
        first_of_this_month = today.replace(day=1)
        start, end = (first_of_this_month - timedelta(days=1)).replace(day=1), first_of_this_month
    else:
        raise ValueError(f"Unknown slack summary cadence: {cadence}")
    return _local_midnight(start, tz), _local_midnight(end, tz)


def get_initial_summary_period(cadence: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The trailing window the first summary covers when an account opts in.

    Deliberately wider than the cadence, because one closed day of a quiet channel is
    rarely worth reading and this summary exists to show value immediately. Ends at
    ``now`` rather than local midnight so that today's messages are included.
    """
    local_now = now.astimezone(tz)
    today = local_now.date()
    if cadence in (SlackSummaryCadence.DAILY, SlackSummaryCadence.WEEKLY):
        start = today - timedelta(days=7)
    elif cadence == SlackSummaryCadence.MONTHLY:
        start = today - relativedelta(months=1)
    else:
        raise ValueError(f"Unknown slack summary cadence: {cadence}")
    return _local_midnight(start, tz), local_now


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)
