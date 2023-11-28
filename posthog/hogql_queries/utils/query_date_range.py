import re
from datetime import datetime, timedelta
from functools import cached_property
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from pydantic_core._pydantic_core import ValidationError

from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.parser import ast
from posthog.models.team import Team, WeekStartDay
from posthog.queries.util import get_earliest_timestamp
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

        if not self.is_hourly:
            date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

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
    def interval_name(self) -> str:
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

    def to_placeholders(self) -> Dict[str, ast.Expr]:
        return {
            "interval": self.interval_period_string_as_hogql_constant(),
            "one_interval_period": self.one_interval_period(),
            "number_interval_period": self.number_interval_periods(),
            "date_from": self.date_from_as_hogql(),
            "date_to": self.date_to_as_hogql(),
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
        self._total_intervals = total_intervals
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
            raise ValidationError(f"Period {period} is unsupported.")

        return period_map[period.lower()] * total_intervals

    def date_from(self) -> datetime:
        delta = self.determine_time_delta(self._total_intervals, self._interval.name)

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
