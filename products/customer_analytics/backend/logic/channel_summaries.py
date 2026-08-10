from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from products.customer_analytics.backend.models import SlackSummaryCadence


@dataclass(frozen=True, kw_only=True)
class SummaryPeriod:
    """A half-open ``[start, end)`` window at local midnight in the account team's timezone."""

    start: datetime
    end: datetime


# Daily reaches back a week because one closed day of a quiet channel is rarely worth opening.
_INITIAL_BACKFILL_PERIODS: dict[str, int] = {
    SlackSummaryCadence.DAILY: 7,
    SlackSummaryCadence.WEEKLY: 1,
    SlackSummaryCadence.MONTHLY: 1,
}

_CADENCE_STEP: dict[str, relativedelta] = {
    SlackSummaryCadence.DAILY: relativedelta(days=1),
    SlackSummaryCadence.WEEKLY: relativedelta(weeks=1),
    SlackSummaryCadence.MONTHLY: relativedelta(months=1),
}


def get_last_closed_period(cadence: str, now: datetime, tz: ZoneInfo) -> SummaryPeriod:
    """The most recent fully-elapsed calendar window for ``cadence`` in ``tz``.

    Daily → yesterday, weekly → last ISO week (Monday to Monday), monthly → last
    calendar month.
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
    return SummaryPeriod(start=_local_midnight(start, tz), end=_local_midnight(end, tz))


def get_initial_summary_periods(cadence: str, now: datetime, tz: ZoneInfo) -> list[SummaryPeriod]:
    """Oldest first. Excludes the current partial period, whose summary would claim the
    period key the coordinator later wants for the complete one."""
    count = _INITIAL_BACKFILL_PERIODS.get(cadence)
    if count is None:
        raise ValueError(f"Unknown slack summary cadence: {cadence}")
    step = _CADENCE_STEP[cadence]
    periods = [get_last_closed_period(cadence, now, tz)]
    while len(periods) < count:
        previous_end = periods[-1].start
        periods.append(SummaryPeriod(start=_local_midnight(previous_end.date() - step, tz), end=previous_end))
    return list(reversed(periods))


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)
