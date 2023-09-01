from datetime import datetime, timedelta
from functools import cached_property
from typing import Optional

import pytz
from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.models.team import Team
from posthog.queries.util import PERIOD_TO_TRUNC_FUNC, TIME_IN_SECONDS, get_earliest_timestamp
from posthog.schema import DateRange, IntervalType
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse, relative_date_parse_with_delta_mapping


# Originally copied from posthog/queries/query_date_range.py with some changes to support the new format
class QueryDateRange:
    """Translation of the raw `date_from` and `date_to` filter values to datetimes.

    A raw `date_from` and `date_to` value can either be:
    - unset, in which case `date_from` takes the timestamp of the earliest event in the project and `date_to` equals now
    - a string, which can be a datetime in any format supported by dateutil.parser.isoparse()
    - a datetime already (only for filters constructed internally)
    """

    _team: Team
    _date_range: Optional[DateRange]
    _interval: Optional[IntervalType]
    _now_nontz: datetime

    def __init__(
        self, date_range: Optional[DateRange], team: Team, interval: Optional[IntervalType], now: datetime
    ) -> None:
        self._team = team
        self._date_range = date_range
        self._interval = interval
        self._now_nontz = now

    @cached_property
    def date_to_param(self) -> datetime:
        date_to = self._now
        delta_mapping = None

        if self._date_range and self._date_range.date_to:
            if isinstance(self._date_range.date_to, str):
                date_to, delta_mapping = relative_date_parse_with_delta_mapping(
                    self._date_range.date_to, self._team.timezone_info, always_truncate=True
                )
            elif isinstance(self._date_range.date_to, datetime):
                date_to = self._localize_to_team(self._date_range.date_to)

        is_relative = not self._date_range or not self._date_range.date_to or delta_mapping is not None
        if not self.is_hourly():
            date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif is_relative:
            date_to = date_to.replace(minute=59, second=59, microsecond=999999)

        return date_to

    def get_earliest_timestamp(self):
        return get_earliest_timestamp(self._team.pk)

    @cached_property
    def date_from_param(self) -> datetime:
        date_from: datetime
        if self._date_range and self._date_range.date_from == "all":
            date_from = self.get_earliest_timestamp()
        elif self._date_range and isinstance(self._date_range.date_from, str):
            date_from = relative_date_parse(self._date_range.date_from, self._team.timezone_info)
        elif self._date_range and isinstance(self._date_range.date_from, datetime):
            date_from = self._localize_to_team(self._date_range.date_from)
        else:
            date_from = self._now.replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(
                days=DEFAULT_DATE_FROM_DAYS
            )

        if not self.is_hourly():
            date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

        return date_from

    @cached_property
    def _now(self):
        return self._localize_to_team(self._now_nontz)

    @cached_property
    def timezone(self):
        return self._team.timezone

    def _localize_to_team(self, target: datetime):
        return target.astimezone(pytz.timezone(self._team.timezone))

    @cached_property
    def interval_annotation(self) -> str:
        interval = self._interval
        if interval is None:
            interval = "day"
        ch_function = PERIOD_TO_TRUNC_FUNC.get(interval.lower())
        if ch_function is None:
            raise ValidationError(f"Period {interval} is unsupported.")
        return ch_function

    # @cached_property
    # def date_to_clause(self):
    #     return self._get_timezone_aware_date_condition("date_to")
    #
    # @cached_property
    # def date_from_clause(self):
    #     return self._get_timezone_aware_date_condition("date_from")

    @cached_property
    def date_to(self) -> str:
        date_to = self.date_to_param

        return date_to.strftime("%Y-%m-%d %H:%M:%S")

    @cached_property
    def date_from(self) -> str:
        date_from = self.date_from_param

        return date_from.strftime("%Y-%m-%d %H:%M:%S")

    # def _get_timezone_aware_date_condition(self, date_param: Literal["date_from", "date_to"]) -> str:
    #     operator = ">=" if date_param == "date_from" else "<="
    #     event_timestamp_expr = self._normalize_datetime(column=f"{self._table}timestamp")
    #     date_expr = self._normalize_datetime(param=date_param)
    #     if operator == ">=" and self.should_round:  # Round date_from to start of interval if `should_round` is true
    #         date_expr = self._truncate_normalized_datetime(date_expr, self.interval_annotation)
    #     return f"AND {event_timestamp_expr} {operator} {date_expr}"

    @staticmethod
    def _normalize_datetime(*, column: Optional[str] = None, param: Optional[str] = None) -> str:
        """Return expression with datetime normalized to project timezone.

        If normalizing a column (such as `events.timestamp`) provide the column expression as `column`
        (e.g. `"events.timestamp"`). Stored data is already of type `DateTime('UTC')` already, so we just
        need to convert that to the project TZ.
        If normalizing a parameter (such as `%(date_from)s`) provide the parameter name as `param` (e.g. `"date_from"`).
        Such parameters are strings, so they need to be parsed. They're assumed to already be in the project TZ.
        """
        if column and param:
            raise ValueError("Must provide either column or param, not both")
        if column:
            return f"toTimeZone({column}, %(timezone)s)"
        elif param:
            return f"toDateTime(%({param})s, %(timezone)s)"
        else:
            raise ValueError("Must provide either column or param")

    @classmethod
    def _truncate_normalized_datetime(cls, normalized_datetime_expr: str, trunc_func: str) -> str:
        """Return expression with normalized datetime truncated to the start of the interval."""
        extra_trunc_func_args = cls.determine_extra_trunc_func_args(trunc_func)
        # toDateTime is important here, as otherwise we'd get a date in many cases, which breaks comparisons
        return f"toDateTime({trunc_func}({normalized_datetime_expr}{extra_trunc_func_args}), %(timezone)s)"

    @staticmethod
    def determine_extra_trunc_func_args(trunc_func: str) -> str:
        """
        Returns any extra arguments to be passed to the toStartOfWeek, toStartOfMonth, and other date truncation functions.

        Currently only one of those functions requires extra args: toStartOfWeek. It takes a second argument indicating
        if weeks should be Sunday-based (mode=0) or Monday-based (mode=1). We want Sunday-based, so we set that mode to 0.
        """
        return ", 0" if trunc_func == "toStartOfWeek" else ""

    @cached_property
    def delta(self) -> timedelta:
        return self.date_to_param - self.date_from_param

    @cached_property
    def num_intervals(self) -> int:
        if self._interval is None:
            return 1
        if self._interval == "month":
            rel_delta = relativedelta(self.date_to_param, self.date_from_param)
            return (rel_delta.years * 12) + rel_delta.months + 1

        return int(self.delta.total_seconds() / TIME_IN_SECONDS[self._interval]) + 1

    # @cached_property
    # def should_round(self) -> bool:
    #     if self._should_round is not None:
    #         return self._should_round
    #
    #     if not hasattr(self._filter, "interval") or self._filter.use_explicit_dates:
    #         return False
    #
    #     round_interval = False
    #     if self._filter.interval in ["week", "month"]:
    #         round_interval = True
    #     else:
    #         round_interval = self.delta.total_seconds() >= TIME_IN_SECONDS[self._filter.interval] * 2
    #
    #     return round_interval

    def is_hourly(self):
        return self._interval and self._interval.name == "hour"
