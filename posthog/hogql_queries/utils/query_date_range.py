import re
from datetime import datetime, timedelta
from functools import cached_property
from typing import Literal, Optional, Dict, List
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import ast
from posthog.models.team import Team, WeekStartDay
from posthog.queries.util import get_earliest_timestamp, get_trunc_func_ch
from posthog.schema import DateRange, IntervalType
from posthog.utils import (
    DEFAULT_DATE_FROM_DAYS,
    relative_date_parse,
    relative_date_parse_with_delta_mapping,
)


# Originally similar to posthog/queries/query_date_range.py but rewritten to be used in HogQL queries
class QueryDateRange:
    """Translation of the raw `date_from` and `date_to` filter values to datetimes."""

    _team: Team
    _date_range: Optional[DateRange]
    _interval: Optional[IntervalType]
    _now_without_timezone: datetime

    def __init__(
        self,
        date_range: Optional[DateRange],
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
    ) -> None:
        self._team = team
        self._date_range = date_range
        self._interval = interval or IntervalType.day
        self._now_without_timezone = now

        if not isinstance(self._interval, IntervalType) or re.match(r"[^a-z]", self._interval.name):
            raise ValueError(f"Invalid interval: {interval}")

    def date_to(self) -> datetime:
        date_to = self.now_with_timezone
        delta_mapping = None

        if self._date_range and self._date_range.date_to:
            date_to, delta_mapping, _position = relative_date_parse_with_delta_mapping(
                self._date_range.date_to,
                self._team.timezone_info,
                always_truncate=True,
                now=self.now_with_timezone,
            )

        is_relative = not self._date_range or not self._date_range.date_to or delta_mapping is not None
        if not self.is_hourly:
            date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif is_relative:
            date_to = date_to.replace(minute=59, second=59, microsecond=999999)

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
    def is_hourly(self) -> bool:
        return self.interval_name == "hour"

    @cached_property
    def interval_type(self) -> IntervalType:
        return self._interval or IntervalType.day

    @cached_property
    def interval_name(self) -> Literal["hour", "day", "week", "month"]:
        return self.interval_type.name

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

        if interval == IntervalType.hour:
            return False
        elif interval == IntervalType.day:
            if is_delta_hours:
                return False
            else:
                return True
        elif interval == IntervalType.week or interval == IntervalType.month:
            return True

        return True

    def date_to_start_of_interval_hogql(self, date: ast.Expr) -> ast.Call:
        match self.interval_name:
            case "hour":
                return ast.Call(name="toStartOfHour", args=[date])
            case "day":
                return ast.Call(name="toStartOfDay", args=[date])
            case "week":
                return ast.Call(name="toStartOfWeek", args=[date])
            case "month":
                return ast.Call(name="toStartOfMonth", args=[date])
            case _:
                raise HogQLException(message="Unknown interval name")

    def date_from_to_start_of_interval_hogql(self) -> ast.Call:
        return self.date_to_start_of_interval_hogql(self.date_from_as_hogql())

    def date_to_to_start_of_interval_hogql(self) -> ast.Call:
        return self.date_to_start_of_interval_hogql(self.date_to_as_hogql())

    def to_placeholders(self) -> Dict[str, ast.Expr]:
        return {
            "interval": self.interval_period_string_as_hogql_constant(),
            "one_interval_period": self.one_interval_period(),
            "number_interval_period": self.number_interval_periods(),
            "date_from": self.date_from_as_hogql(),
            "date_to": self.date_to_as_hogql(),
            "date_from_start_of_interval": self.date_from_to_start_of_interval_hogql(),
            "date_to_start_of_interval": self.date_to_to_start_of_interval_hogql(),
            "date_from_with_adjusted_start_of_interval": self.date_from_to_start_of_interval_hogql()
            if self.use_start_of_interval()
            else self.date_from_as_hogql(),
        }

    def to_properties(self, field: Optional[List[str]] = None) -> List[ast.Expr]:
        if not field:
            field = ["timestamp"]
        return [
            ast.CompareOperation(
                left=ast.Field(chain=field),
                op=CompareOperationOp.LtEq,
                right=self.date_to_as_hogql(),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=field),
                op=CompareOperationOp.Gt,
                right=self.date_to_as_hogql(),
            ),
        ]


class QueryDateRangeWithIntervals(QueryDateRange):
    def __init__(
        self,
        date_range: Optional[DateRange],
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

        if self._interval == IntervalType.hour:
            return self.date_to() - delta
        elif self._interval == IntervalType.week:
            date_from = self.date_to() - delta
            week_start_alignment_days = date_from.isoweekday() % 7
            if self._team.week_start_day == WeekStartDay.MONDAY:
                week_start_alignment_days = date_from.weekday()
            return date_from - timedelta(days=week_start_alignment_days)
        else:
            date_to = self.date_to().replace(hour=0, minute=0, second=0, microsecond=0)
            return date_to - delta

    def date_to(self) -> datetime:
        delta = self.determine_time_delta(1, self._interval.name)
        date_to = super().date_to() + delta

        if self.is_hourly:
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
