from datetime import datetime
from functools import cached_property, lru_cache
from typing import Optional

import pytz
from dateutil.relativedelta import relativedelta

from posthog.hogql.parser import parse_expr, ast
from posthog.models.team import Team
from posthog.queries.util import get_earliest_timestamp
from posthog.schema import DateRange, IntervalType
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse, relative_date_parse_with_delta_mapping


# Originally copied from posthog/queries/query_date_range.py with some changes to support the new format
class QueryDateRange:
    """Translation of the raw `date_from` and `date_to` filter values to datetimes."""

    _team: Team
    _date_range: Optional[DateRange]
    _interval: Optional[IntervalType]
    _now_non_timezone: datetime

    def __init__(
        self, date_range: Optional[DateRange], team: Team, interval: Optional[IntervalType], now: datetime
    ) -> None:
        self._team = team
        self._date_range = date_range
        self._interval = interval
        self._now_non_timezone = now

    @cached_property
    def date_to(self) -> datetime:
        date_to = self._now
        delta_mapping = None

        if self._date_range and self._date_range.date_to:
            date_to, delta_mapping = relative_date_parse_with_delta_mapping(
                self._date_range.date_to, self._team.timezone_info, always_truncate=True
            )

        is_relative = not self._date_range or not self._date_range.date_to or delta_mapping is not None
        if not self.is_hourly():
            date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif is_relative:
            date_to = date_to.replace(minute=59, second=59, microsecond=999999)

        return date_to

    def get_earliest_timestamp(self):
        return get_earliest_timestamp(self._team.pk)

    @cached_property
    def date_from(self) -> datetime:
        date_from: datetime
        if self._date_range and self._date_range.date_from == "all":
            date_from = self.get_earliest_timestamp()
        elif self._date_range and isinstance(self._date_range.date_from, str):
            date_from = relative_date_parse(self._date_range.date_from, self._team.timezone_info)
        else:
            date_from = self._now.replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(
                days=DEFAULT_DATE_FROM_DAYS
            )

        if not self.is_hourly():
            date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

        return date_from

    @cached_property
    def _now(self):
        return self._localize_to_team(self._now_non_timezone)

    def _localize_to_team(self, target: datetime):
        return target.astimezone(pytz.timezone(self._team.timezone))

    @cached_property
    def date_to_str(self) -> str:
        return self.date_to.strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def date_from_str(self) -> str:
        return self.date_from.strftime("%Y-%m-%d %H:%M:%S")

    def is_hourly(self):
        return self.interval.name == "hour"

    @cached_property
    def date_to_as_hogql(self):
        return parse_expr(f"assumeNotNull(toDateTime('{self.date_to_str}'))")

    @cached_property
    def date_from_as_hogql(self):
        return parse_expr(f"assumeNotNull(toDateTime('{self.date_from_str}'))")

    @cached_property
    def interval(self):
        return self._interval or IntervalType.day

    @cached_property
    def one_interval_period_as_hogql(self):
        return parse_expr(f"toInterval{self.interval.capitalize()}(1)")

    @lru_cache
    def interval_periods_as_hogql(self, s: str):
        return parse_expr(f"toInterval{self.interval.capitalize()}({s})")

    @cached_property
    def interval_period_string(self):
        return self.interval.value

    @cached_property
    def interval_period_string_as_hogql(self):
        return ast.Constant(value=self.interval.value)
