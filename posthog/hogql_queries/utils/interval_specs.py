from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional, Union

from dateutil.relativedelta import relativedelta

from posthog.schema_enums import IntervalType

IntervalLiteral = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]


class UnsupportedIntervalError(ValueError):
    pass


def _align_second(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(microsecond=0)


def _align_minute(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(second=0, microsecond=0)


def _align_hour(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(minute=0, second=0, microsecond=0)


def _align_day(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


def _align_week(date: datetime, week_start_day: Optional[int]) -> datetime:
    date = _align_day(date, week_start_day)
    if week_start_day == 1:  # WeekStartDay.MONDAY
        alignment_days = date.weekday()
    else:
        alignment_days = date.isoweekday() % 7
    return date - timedelta(days=alignment_days)


def _align_month(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _align_quarter(date: datetime, week_start_day: Optional[int]) -> datetime:
    quarter_start_month = ((date.month - 1) // 3) * 3 + 1
    return date.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _align_year(date: datetime, week_start_day: Optional[int]) -> datetime:
    return date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class IntervalSpec:
    """Everything the query layer knows about one interval size — adding an interval means adding one entry to INTERVAL_SPECS."""

    interval_type: IntervalType
    # ClickHouse toStartOf* function, None when ClickHouse has no DateTime-compatible one
    trunc_func: Optional[str]
    interval_func: str
    relativedelta_kwarg: str
    period: Union[timedelta, relativedelta]
    align: Callable[[datetime, Optional[int]], datetime]
    staleness_default: Optional[timedelta]
    staleness_lazy: Optional[timedelta]
    # For intervals relativedelta has no kwarg for (a quarter is months=3)
    relativedelta_multiplier: int = 1


# Ordered smallest to largest — ORDERED_INTERVALS derives interval comparison from this order
INTERVAL_SPECS: dict[IntervalLiteral, IntervalSpec] = {
    "second": IntervalSpec(
        interval_type=IntervalType.SECOND,
        trunc_func=None,  # toStartOfSecond only supports DateTime64
        interval_func="toIntervalSecond",
        relativedelta_kwarg="seconds",
        period=timedelta(seconds=1),
        align=_align_second,
        staleness_default=None,
        staleness_lazy=None,
    ),
    "minute": IntervalSpec(
        interval_type=IntervalType.MINUTE,
        trunc_func="toStartOfMinute",
        interval_func="toIntervalMinute",
        relativedelta_kwarg="minutes",
        period=timedelta(minutes=1),
        align=_align_minute,
        staleness_default=timedelta(minutes=5),
        staleness_lazy=timedelta(minutes=15),
    ),
    "hour": IntervalSpec(
        interval_type=IntervalType.HOUR,
        trunc_func="toStartOfHour",
        interval_func="toIntervalHour",
        relativedelta_kwarg="hours",
        period=timedelta(hours=1),
        align=_align_hour,
        staleness_default=timedelta(hours=1),
        staleness_lazy=timedelta(hours=2),
    ),
    "day": IntervalSpec(
        interval_type=IntervalType.DAY,
        trunc_func="toStartOfDay",
        interval_func="toIntervalDay",
        relativedelta_kwarg="days",
        period=timedelta(days=1),
        align=_align_day,
        staleness_default=timedelta(hours=6),
        staleness_lazy=timedelta(hours=12),
    ),
    "week": IntervalSpec(
        interval_type=IntervalType.WEEK,
        trunc_func="toStartOfWeek",
        interval_func="toIntervalWeek",
        relativedelta_kwarg="weeks",
        period=timedelta(weeks=1),
        align=_align_week,
        staleness_default=timedelta(days=1),
        staleness_lazy=timedelta(days=1),
    ),
    "month": IntervalSpec(
        interval_type=IntervalType.MONTH,
        trunc_func="toStartOfMonth",
        interval_func="toIntervalMonth",
        relativedelta_kwarg="months",
        period=relativedelta(months=1),
        align=_align_month,
        staleness_default=timedelta(days=1),
        staleness_lazy=timedelta(days=1),
    ),
    "quarter": IntervalSpec(
        interval_type=IntervalType.QUARTER,
        trunc_func="toStartOfQuarter",
        interval_func="toIntervalQuarter",
        relativedelta_kwarg="months",
        relativedelta_multiplier=3,
        period=relativedelta(months=3),
        align=_align_quarter,
        staleness_default=timedelta(days=1),
        staleness_lazy=timedelta(days=1),
    ),
    "year": IntervalSpec(
        interval_type=IntervalType.YEAR,
        trunc_func="toStartOfYear",
        interval_func="toIntervalYear",
        relativedelta_kwarg="years",
        period=relativedelta(years=1),
        align=_align_year,
        staleness_default=timedelta(days=1),
        staleness_lazy=timedelta(days=1),
    ),
}

ORDERED_INTERVALS: list[IntervalType] = [spec.interval_type for spec in INTERVAL_SPECS.values()]

PERIOD_MAP: dict[str, Union[timedelta, relativedelta]] = {name: spec.period for name, spec in INTERVAL_SPECS.items()}


def interval_spec(interval: Union[IntervalType, str, None]) -> IntervalSpec:
    if interval is None:
        key = "day"
    elif isinstance(interval, IntervalType):
        key = interval.value
    else:
        key = interval.lower()
    spec = INTERVAL_SPECS.get(key)  # type: ignore[arg-type]
    if spec is None:
        raise UnsupportedIntervalError(f"Interval {interval!r} is unsupported")
    return spec


def get_trunc_func(interval: Union[IntervalType, str, None]) -> str:
    spec = interval_spec(interval)
    if spec.trunc_func is None:
        raise UnsupportedIntervalError(f"Interval {spec.interval_type} has no ClickHouse truncation function")
    return spec.trunc_func


def get_interval_func(interval: Union[IntervalType, str, None]) -> str:
    return interval_spec(interval).interval_func
