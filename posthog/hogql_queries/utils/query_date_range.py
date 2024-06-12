import re
from datetime import datetime, timedelta
from functools import cached_property
from typing import cast, Literal, Optional
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.hogql.errors import ImpossibleASTError
from posthog.hogql.parser import ast
from posthog.models.team import Team, WeekStartDay
from posthog.queries.util import get_earliest_timestamp, get_trunc_func_ch
from posthog.schema import DateRange, InsightDateRange, IntervalType
from posthog.utils import (
    DEFAULT_DATE_FROM_DAYS,
    relative_date_parse,
    relative_date_parse_with_delta_mapping,
)

IntervalLiteral = Literal["minute", "hour", "day", "week", "month"]


# Originally similar to posthog/queries/query_date_range.py but rewritten to be used in HogQL queries
class QueryDateRange:
    """Translation of the raw `date_from` and `date_to` filter values to datetimes."""

    _team: Team
    _date_range: Optional[InsightDateRange | DateRange]
    _interval: Optional[IntervalType]
    _now_without_timezone: datetime

    def __init__(
        self,
        date_range: Optional[InsightDateRange | DateRange],
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
    ) -> None:
        self._team = team
        self._date_range = date_range
        self._interval = interval or IntervalType.DAY
        self._now_without_timezone = now

        if not isinstance(self._interval, IntervalType) or re.match(r"[^a-z]", "DAY", re.IGNORECASE):
            raise ValueError(f"Invalid interval: {interval}")

    def date_to(self) -> datetime:
        date_to = self.now_with_timezone
        delta_mapping = None

        if self._date_range and self._date_range.date_to:
            date_to, delta_mapping, _position = relative_date_parse_with_delta_mapping(
                self._date_range.date_to,
                self._team.timezone_info,
                always_truncate=False,
                now=self.now_with_timezone,
            )

        if not self._date_range or not self._date_range.explicitDate:
            is_relative = not self._date_range or not self._date_range.date_to or delta_mapping is not None

            if self.interval_name not in ("hour", "minute"):
                date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif is_relative:
                if self.interval_name == "hour":
                    date_to = date_to.replace(minute=59, second=59, microsecond=999999)
                else:
                    date_to = date_to.replace(second=59, microsecond=999999)

        return date_to

    def get_earliest_timestamp(self) -> datetime:
        return get_earliest_timestamp(self._team.pk)

    def date_from(self) -> datetime:
        date_from: datetime
        if self._date_range and self._date_range.date_from == "all":
            date_from = self.get_earliest_timestamp()
        elif self._date_range and isinstance(self._date_range.date_from, str):
            date_from = relative_date_parse(
                self._date_range.date_from,
                self._team.timezone_info,
                now=self.now_with_timezone,
                # this makes sure we truncate date_from to the start of the day, when looking at last N days by hour
                # when we look at graphs by minute (last hour or last three hours), don't truncate
                always_truncate=self.interval_name != "minute",
            )
        else:
            date_from = self.now_with_timezone.replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(
                days=DEFAULT_DATE_FROM_DAYS
            )

        return date_from

    @cached_property
    def previous_period_date_from(self) -> datetime:
        return self.date_from() - (self.date_to() - self.date_from())

    @cached_property
    def now_with_timezone(self) -> datetime:
        return self._now_without_timezone.astimezone(ZoneInfo(self._team.timezone))

    @cached_property
    def date_to_str(self) -> str:
        return self.date_to().strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def date_from_str(self) -> str:
        return self.date_from().strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def previous_period_date_from_str(self) -> str:
        return self.previous_period_date_from.strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def interval_type(self) -> IntervalType:
        return self._interval or IntervalType.DAY

    @cached_property
    def interval_name(self) -> IntervalLiteral:
        return cast(IntervalLiteral, self.interval_type.name.lower())

    @cached_property
    def is_hourly(self) -> bool:
        if self._interval is None:
            return False

        return self._interval == IntervalType.HOUR

    @cached_property
    def explicit(self) -> bool:
        if self._date_range is None or self._date_range.explicitDate is None:
            return False

        return self._date_range.explicitDate

    def align_with_interval(self, start: datetime) -> datetime:
        if self.interval_name == "minute":
            return start.replace(second=0, microsecond=0)
        if self.interval_name == "hour":
            return start.replace(minute=0, second=0, microsecond=0)
        elif self.interval_name == "day":
            return start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self.interval_name == "week":
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start_alignment_days = start.isoweekday() % 7
            if self._team.week_start_day == WeekStartDay.MONDAY:
                week_start_alignment_days = start.weekday()
            start -= timedelta(days=week_start_alignment_days)
            return start
        elif self.interval_name == "month":
            return start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def interval_relativedelta(self) -> relativedelta:
        return relativedelta(
            days=1 if self.interval_name == "day" else 0,
            weeks=1 if self.interval_name == "week" else 0,
            months=1 if self.interval_name == "month" else 0,
            hours=1 if self.interval_name == "hour" else 0,
            minutes=1 if self.interval_name == "minute" else 0,
        )

    def all_values(self) -> list[datetime]:
        start = self.align_with_interval(self.date_from())
        end: datetime = self.date_to()
        delta = self.interval_relativedelta()

        values: list[datetime] = []
        while start <= end:
            values.append(start)
            start += delta
        return values

    def date_to_as_hogql(self) -> ast.Expr:
        return ast.Call(
            name="assumeNotNull",
            args=[ast.Call(name="toDateTime", args=[(ast.Constant(value=self.date_to_str))])],
        )

    def date_from_as_hogql(self) -> ast.Expr:
        return ast.Call(
            name="assumeNotNull",
            args=[ast.Call(name="toDateTime", args=[(ast.Constant(value=self.date_from_str))])],
        )

    def previous_period_date_from_as_hogql(self) -> ast.Expr:
        return ast.Call(
            name="assumeNotNull",
            args=[
                ast.Call(
                    name="toDateTime",
                    args=[(ast.Constant(value=self.previous_period_date_from_str))],
                )
            ],
        )

    def one_interval_period(self) -> ast.Expr:
        return ast.Call(
            name=f"toInterval{self.interval_name.capitalize()}",
            args=[ast.Constant(value=1)],
        )

    def number_interval_periods(self) -> ast.Expr:
        return ast.Call(
            name=f"toInterval{self.interval_name.capitalize()}",
            args=[ast.Field(chain=["number"])],
        )

    def interval_period_string_as_hogql_constant(self) -> ast.Expr:
        return ast.Constant(value=self.interval_name)

    # Returns whether we should wrap `date_from` with `toStartOf<Interval>` dependent on the interval period
    def use_start_of_interval(self):
        if self._date_range is None or self._date_range.date_from is None:
            return True

        _date_from, delta_mapping, _position = relative_date_parse_with_delta_mapping(
            self._date_range.date_from,
            self._team.timezone_info,
            always_truncate=True,
            now=self.now_with_timezone,
        )

        is_relative = delta_mapping is not None
        interval = self._interval

        if not is_relative or not interval:
            return True

        is_delta_hours = delta_mapping.get("hours", None) is not None

        if interval in (IntervalType.HOUR, IntervalType.MINUTE):
            return False
        elif interval == IntervalType.DAY:
            if is_delta_hours:
                return False
        return True

    def date_to_start_of_interval_hogql(self, date: ast.Expr) -> ast.Call:
        match self.interval_name:
            case "minute":
                return ast.Call(name="toStartOfMinute", args=[date])
            case "hour":
                return ast.Call(name="toStartOfHour", args=[date])
            case "day":
                return ast.Call(name="toStartOfDay", args=[date])
            case "week":
                return ast.Call(name="toStartOfWeek", args=[date])
            case "month":
                return ast.Call(name="toStartOfMonth", args=[date])
            case _:
                raise ImpossibleASTError(message="Unknown interval name")

    def date_from_to_start_of_interval_hogql(self) -> ast.Call:
        return self.date_to_start_of_interval_hogql(self.date_from_as_hogql())

    def date_to_to_start_of_interval_hogql(self) -> ast.Call:
        return self.date_to_start_of_interval_hogql(self.date_to_as_hogql())

    def date_to_with_extra_interval_hogql(self) -> ast.Call:
        return ast.Call(
            name="plus",
            args=[self.date_to_start_of_interval_hogql(self.date_to_as_hogql()), self.one_interval_period()],
        )

    def to_placeholders(self) -> dict[str, ast.Expr]:
        return {
            "interval": self.interval_period_string_as_hogql_constant(),
            "one_interval_period": self.one_interval_period(),
            "number_interval_period": self.number_interval_periods(),
            "date_from": self.date_from_as_hogql(),
            "date_to": self.date_to_as_hogql(),
            "date_from_start_of_interval": self.date_from_to_start_of_interval_hogql(),
            "date_to_start_of_interval": self.date_to_to_start_of_interval_hogql(),
            "date_from_with_adjusted_start_of_interval": (
                self.date_from_to_start_of_interval_hogql()
                if self.use_start_of_interval()
                else self.date_from_as_hogql()
            ),
        }


class QueryDateRangeWithIntervals(QueryDateRange):
    def __init__(
        self,
        date_range: Optional[InsightDateRange],
        total_intervals: int,
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
    ) -> None:
        self.total_intervals = total_intervals
        super().__init__(date_range, team, interval, now)

    @staticmethod
    def determine_time_delta(total_intervals: int, period: str) -> timedelta:
        period_map = {
            "minute": timedelta(minutes=1),
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
            "month": relativedelta(months=1),
        }

        if period.lower() not in period_map:
            raise ValueError(f"Period {period} is unsupported.")

        return period_map[period.lower()] * total_intervals

    def date_from(self) -> datetime:
        delta = self.determine_time_delta(self.total_intervals, self._interval.name)

        if self._interval in (IntervalType.HOUR, IntervalType.MINUTE):
            return self.date_to() - delta
        elif self._interval == IntervalType.WEEK:
            date_from = self.date_to() - delta
            week_start_alignment_days = date_from.isoweekday() % 7
            if self._team.week_start_day == WeekStartDay.MONDAY:
                week_start_alignment_days = date_from.weekday()
            return date_from - timedelta(days=week_start_alignment_days)
        elif self._interval == IntervalType.MONTH:
            return self.date_to().replace(day=1, hour=0, minute=0, second=0, microsecond=0) - delta
        else:
            date_to = self.date_to().replace(hour=0, minute=0, second=0, microsecond=0)
            return date_to - delta

    def date_to(self) -> datetime:
        delta = self.determine_time_delta(1, self._interval.name)
        date_to = super().date_to() + delta

        if self.interval_name == "minute":
            return date_to.replace(second=0, microsecond=0)
        if self.interval_name == "hour":
            return date_to.replace(minute=0, second=0, microsecond=0)
        return date_to.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_start_of_interval_hogql(self, *, source: ast.Expr = None) -> ast.Expr:
        trunc_func = get_trunc_func_ch(self._interval.name.lower())
        trunc_func_args = [source] if source else [ast.Constant(value=self.date_from())]
        if trunc_func == "toStartOfWeek":
            trunc_func_args.append(
                ast.Constant(value=int((WeekStartDay(self._team.week_start_day or 0)).clickhouse_mode))
            )
        return ast.Call(name=trunc_func, args=trunc_func_args)
