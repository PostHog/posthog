from datetime import datetime, timedelta
from functools import cached_property
from typing import Literal, Optional, cast
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.schema import DateRange, IntervalType

from posthog.hogql.parser import ast

from posthog.models.team import Team, WeekStartDay
from posthog.queries.util import get_earliest_timestamp, get_trunc_func_ch
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse, relative_date_parse_with_delta_mapping

IntervalLiteral = Literal["minute", "hour", "day", "week", "month"]
ORDERED_INTERVALS = [IntervalType.MINUTE, IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH]


def compare_interval_length(
    interval1: IntervalType, operator: Literal["<", "<=", "=", ">", ">="], interval2: IntervalType
) -> bool:
    if operator == "<":
        return ORDERED_INTERVALS.index(interval1) < ORDERED_INTERVALS.index(interval2)
    elif operator == "<=":
        return ORDERED_INTERVALS.index(interval1) <= ORDERED_INTERVALS.index(interval2)
    elif operator == "=":
        return ORDERED_INTERVALS.index(interval1) == ORDERED_INTERVALS.index(interval2)
    elif operator == ">":
        return ORDERED_INTERVALS.index(interval1) > ORDERED_INTERVALS.index(interval2)
    elif operator == ">=":
        return ORDERED_INTERVALS.index(interval1) >= ORDERED_INTERVALS.index(interval2)


# Originally similar to posthog/queries/query_date_range.py but rewritten to be used in HogQL queries
class QueryDateRange:
    """Translation of the raw `date_from` and `date_to` filter values to datetimes."""

    _team: Team
    _date_range: Optional[DateRange]
    _interval: Optional[IntervalType]
    _interval_count: int
    _now_without_timezone: datetime
    _earliest_timestamp_fallback: Optional[datetime]

    def __init__(
        self,
        date_range: Optional[DateRange],
        team: Team,
        interval: Optional[IntervalType],
        now: datetime,
        earliest_timestamp_fallback: Optional[datetime] = None,
        interval_count: Optional[int] = None,
        timezone_info: Optional[ZoneInfo] = None,
        exact_timerange: bool = False,  # Setting this to true stops a relative time range from including the time between the intervalStart and the date_range start, as well as cuts off the interval at precisely now()
    ) -> None:
        self._team = team
        self._date_range = date_range
        self._interval = interval or IntervalType.DAY
        self._interval_count = interval_count or 1
        self._now_without_timezone = now
        self._earliest_timestamp_fallback = earliest_timestamp_fallback
        self._timezone_info = timezone_info or self._team.timezone_info
        self._exact_timerange = exact_timerange

        # Hour intervals have strange behaviour in clickhouse:
        # From the docs:
        # (*) hour intervals are special: the calculation is always performed relative to 00:00:00 (midnight) of the current day
        # Keep 1 hour intervals the same just in case there's subtle changes (there shouldn't be)
        # but for other counts switch to 60x minute intervals
        if self._interval == IntervalType.HOUR and self._interval_count > 1:
            self._interval = IntervalType.MINUTE
            self._interval_count *= 60

        if not isinstance(self._interval, IntervalType):
            raise ValueError(f"Value {repr(interval)} is not an instance of IntervalType")
        if self._interval == IntervalType.WEEK and self._interval_count > 1:
            # Due to differences in clickhouse between toStartOfWeek and toStartOfInterval(interval X weeks)
            # we can't support multiple week intervals without breaking backwards compatibility
            raise ValueError("IntervalType.WEEK cannot be used with interval_count > 1")

    def date_to(self) -> datetime:
        date_to = self.now_with_timezone
        delta_mapping = None

        if self._date_range and self._date_range.date_to:
            date_to, delta_mapping, _position = relative_date_parse_with_delta_mapping(
                self._date_range.date_to,
                self._timezone_info,
                always_truncate=False,
                now=self.now_with_timezone,
            )
        elif self._exact_timerange:
            return date_to

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
        if self._earliest_timestamp_fallback:
            return self._earliest_timestamp_fallback

        return get_earliest_timestamp(self._team.pk)

    def date_from(self) -> datetime:
        date_from: datetime
        if self._date_range and self._date_range.date_from == "all":
            date_from = self.get_earliest_timestamp()
        elif self._date_range and isinstance(self._date_range.date_from, str):
            date_from = relative_date_parse(
                self._date_range.date_from,
                self._timezone_info,
                now=self.now_with_timezone,
                # this makes sure we truncate date_from to the start of the day, when looking at last N days by hour
                # when we look at graphs by minute (last hour or last three hours), don't truncate
                always_truncate=not (self.interval_name == "minute" or self._exact_timerange),
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
        return self._now_without_timezone.astimezone(self._timezone_info)

    def format_date(self, datetime) -> str:
        return datetime.strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def date_to_str(self) -> str:
        return self.format_date(self.date_to())

    @cached_property
    def date_from_str(self) -> str:
        return self.format_date(self.date_from())

    @cached_property
    def previous_period_date_from_str(self) -> str:
        return self.format_date(self.previous_period_date_from)

    @cached_property
    def interval_type(self) -> IntervalType:
        return self._interval or IntervalType.DAY

    @cached_property
    def interval_name(self) -> IntervalLiteral:
        return cast(IntervalLiteral, self.interval_type.name.lower())

    @cached_property
    def interval_count(self) -> int:
        return self._interval_count

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

    def align_with_interval(self, start: datetime, *, interval_name: Optional[IntervalLiteral] = None) -> datetime:
        interval_name = interval_name or self.interval_name

        if interval_name == "minute":
            return start.replace(second=0, microsecond=0)
        if interval_name == "hour":
            return start.replace(minute=0, second=0, microsecond=0)
        elif interval_name == "day":
            return start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif interval_name == "week":
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start_alignment_days = start.isoweekday() % 7
            if self._team.week_start_day == WeekStartDay.MONDAY:
                week_start_alignment_days = start.weekday()
            start -= timedelta(days=week_start_alignment_days)
            return start
        elif interval_name == "month":
            return start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def interval_relativedelta(self) -> relativedelta:
        return relativedelta(
            days=self.interval_count if self.interval_name == "day" else 0,
            weeks=self.interval_count if self.interval_name == "week" else 0,
            months=self.interval_count if self.interval_name == "month" else 0,
            hours=self.interval_count if self.interval_name == "hour" else 0,
            minutes=self.interval_count if self.interval_name == "minute" else 0,
        )

    def all_values(self, *, interval_name: Optional[IntervalLiteral] = None) -> list[datetime]:
        start = self.align_with_interval(self.date_from(), interval_name=interval_name)
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
            args=[ast.Constant(value=self.interval_count)],
        )

    def number_interval_periods_hogql(self) -> ast.Expr:
        if self.interval_count == 1:
            return ast.Call(
                name=f"toInterval{self.interval_name.capitalize()}",
                args=[ast.Field(chain=["number"])],
            )
        else:
            return ast.Call(
                name=f"toInterval{self.interval_name.capitalize()}",
                args=[
                    ast.Call(
                        name="multiply", args=[ast.Field(chain=["number"]), ast.Constant(value=self.interval_count)]
                    )
                ],
            )

    def interval_period_string_as_hogql_constant(self) -> ast.Expr:
        return ast.Constant(value=self.interval_name)

    def interval_count_as_hogql_constant(self) -> ast.Expr:
        return ast.Constant(value=self._interval_count)

    # Returns whether we should wrap `date_from` with `toStartOf<Interval>` dependent on the interval period
    def use_start_of_interval(self):
        if self._exact_timerange:
            return False

        if self._date_range is None or self._date_range.date_from is None:
            return True

        _date_from, delta_mapping, _position = relative_date_parse_with_delta_mapping(
            self._date_range.date_from,
            self._timezone_info,
            always_truncate=True,
            now=self.now_with_timezone,
        )

        is_relative = delta_mapping is not None
        interval = self._interval

        if self._date_range.explicitDate:
            return False

        if not is_relative or not interval:
            return True

        is_delta_hours = delta_mapping and delta_mapping.get("hours", None) is not None

        if interval in (IntervalType.HOUR, IntervalType.MINUTE):
            return False
        elif interval == IntervalType.DAY:
            if is_delta_hours:
                return False
        return True

    def date_to_start_of_interval_hogql(self, date: ast.Expr) -> ast.Call:
        match self.interval_name:
            case "week":
                # toStartOfWeek is incompatible with toStartOfInterval:
                #   toStartOfInterval assumes that weeks start on Monday.
                #   Note that this behavior is different from that of function toStartOfWeek in which weeks start by default on Sunday.
                # include this special case for backwards compatibility.
                # interval_count will always be 1 here.
                return ast.Call(name="toStartOfWeek", args=[date])
            case _:
                return ast.Call(name="toStartOfInterval", args=[date, self.one_interval_period()])

    def date_from_to_start_of_interval_hogql(self) -> ast.Call:
        return self.date_to_start_of_interval_hogql(self.date_from_as_hogql())

    def date_from_with_adjusted_start_of_interval_hogql(self) -> ast.Call:
        if self.interval_name == "week":
            # in `where` queries with week intervals, we need to return the date_from instead of the start of the week
            # this ensures that we only fetch records after the date_from
            return ast.Call(
                name="toStartOfInterval",
                args=[
                    self.date_from_as_hogql(),
                    ast.Call(
                        name=f"toIntervalDay",
                        args=[ast.Constant(value=1)],
                    ),
                ],
            )

        return self.date_from_to_start_of_interval_hogql()

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
            "interval_count": self.interval_count_as_hogql_constant(),
            "one_interval_period": self.one_interval_period(),
            "number_interval_period": self.number_interval_periods_hogql(),
            "date_from": self.date_from_as_hogql(),
            "date_to": self.date_to_as_hogql(),
            "date_from_start_of_interval": self.date_from_to_start_of_interval_hogql(),
            "date_to_start_of_interval": self.date_to_to_start_of_interval_hogql(),
            "date_from_with_adjusted_start_of_interval": (
                self.date_from_with_adjusted_start_of_interval_hogql()
                if self.use_start_of_interval()
                else self.date_from_as_hogql()
            ),
        }


PERIOD_MAP: dict[str, timedelta | relativedelta] = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": relativedelta(months=1),
}


class QueryDateRangeWithIntervals(QueryDateRange):
    """
    Only used in retention queries where we need to figure out date_from
    from total_intervals and date_to
    """

    def __init__(
        self,
        date_range: Optional[DateRange],
        total_intervals: int,
        team: Team,
        interval: IntervalType,
        now: datetime,
    ) -> None:
        super().__init__(date_range, team, interval, now)
        # intervals to look ahead for return event
        self.lookahead = total_intervals

    @staticmethod
    def determine_time_delta(interval: int, period: str) -> timedelta:
        if period.lower() not in PERIOD_MAP:
            raise ValueError(f"Period {period} is unsupported.")

        return cast(timedelta, PERIOD_MAP[period.lower()]) * interval

    @cached_property
    def intervals_between(self):
        """
        Number of intervals between date_from and date_to
        """
        assert self._interval

        date_from = self.date_from()
        delta = PERIOD_MAP[self._interval.lower()]

        intervals = 0
        while date_from < self.date_to():
            date_from = date_from + delta
            intervals += 1

        return intervals

    def date_from(self) -> datetime:
        assert self._interval

        # if date_from is present in retention query then use it
        if self._date_range and self._date_range.date_from:
            date_from = super().date_from()
            return date_to_start_of_interval(date_from, self._interval, self._team)

        # otherwise calculate from date_to and lookahead
        # needed to support old retention queries (before date range update in Jan 2025)
        delta = self.determine_time_delta(self.lookahead, self._interval.name)

        return date_to_start_of_interval(self.date_to() - delta, self._interval, self._team)

    def date_to(self) -> datetime:
        assert self._interval

        # add padding for one more interval after date_to and then truncate
        # to start of that interval, to ensure we always compute complete intervals
        delta = self.determine_time_delta(1, self._interval.name)
        date_to = date_to_start_of_interval(super().date_to() + delta, self._interval, self._team)

        return date_to

    def get_start_of_interval_hogql(self, *, source: ast.Expr = None) -> ast.Expr:
        trunc_func = get_trunc_func_ch(self._interval.name.lower())
        trunc_func_args = [source] if source else [ast.Constant(value=self.date_from())]
        if trunc_func == "toStartOfWeek":
            trunc_func_args.append(
                ast.Constant(value=int((WeekStartDay(self._team.week_start_day or 0)).clickhouse_mode))
            )
        return ast.Call(name=trunc_func, args=trunc_func_args)


def date_to_start_of_interval(date: datetime, interval: IntervalType, team: Team) -> datetime:
    match interval:
        case IntervalType.HOUR:
            return date.replace(minute=0, second=0, microsecond=0)
        case IntervalType.DAY:
            return date.replace(hour=0, minute=0, second=0, microsecond=0)
        case IntervalType.WEEK:
            week_start_alignment_days = date.isoweekday() % 7
            if team.week_start_day == WeekStartDay.MONDAY:
                week_start_alignment_days = date.weekday()

            return (date - timedelta(days=week_start_alignment_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        case IntervalType.MONTH:
            return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        case _:
            raise ValueError(f"Unsupported interval {interval}")
