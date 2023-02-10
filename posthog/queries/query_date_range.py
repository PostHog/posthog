from datetime import datetime, timedelta
from functools import cached_property
from typing import Dict, Generic, Literal, Optional, Tuple, TypeVar

import pytz
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.models.filters.mixins.common import DateMixin
from posthog.models.filters.mixins.interval import IntervalMixin
from posthog.models.team import Team
from posthog.queries.util import PERIOD_TO_TRUNC_FUNC, TIME_IN_SECONDS, get_earliest_timestamp
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse_with_delta_mapping

F = TypeVar("F", DateMixin, IntervalMixin)


# Assume that any date being sent from the client is timezone aware according to the timezone that the team has set
class QueryDateRange(Generic[F]):
    _filter: F
    _team: Team
    _table: str
    _should_round: Optional[bool]

    def __init__(self, filter: F, team: Team, should_round: Optional[bool] = None, table="") -> None:
        self._filter = filter
        self._team = team
        self._table = f"{table}." if table else ""
        self._should_round = should_round

    @cached_property
    def date_to_param(self) -> datetime:
        if isinstance(self._filter, IntervalMixin) and not self._filter._date_to and self._filter.interval == "hour":
            return self._now + relativedelta(minutes=1)

        date_to = self._now
        delta_mapping: Optional[Dict[str, int]] = None
        if isinstance(self._filter._date_to, str):
            date_to, delta_mapping = relative_date_parse_with_delta_mapping(self._filter._date_to, now=self._now)
        elif isinstance(self._filter._date_to, datetime):
            date_to = self._localize_to_team(self._filter._date_to)

        if not self._filter.use_explicit_dates:
            if self._is_hourly(delta_mapping):
                date_to = date_to.replace(minute=59, second=59, microsecond=999999)
            else:
                date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)

        return date_to

    def get_earliest_timestamp(self):
        try:
            earliest_date = get_earliest_timestamp(self._team.pk)
        except IndexError:
            return timezone.now()  # TODO: fix
        else:
            return earliest_date

    @cached_property
    def date_from_param(self) -> datetime:
        date_from: datetime
        delta_mapping: Optional[Dict[str, int]] = None
        if self._filter._date_from == "all":
            date_from = self.get_earliest_timestamp()
        elif isinstance(self._filter._date_from, str):
            date_from, delta_mapping = relative_date_parse_with_delta_mapping(self._filter._date_from, now=self._now)
        elif isinstance(self._filter._date_from, datetime):
            date_from = self._localize_to_team(self._filter._date_from)
        else:
            date_from = self._now.replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(
                days=DEFAULT_DATE_FROM_DAYS
            )

        if not self._filter.use_explicit_dates:
            if self._is_hourly(delta_mapping):
                date_from = date_from.replace(minute=0, second=0, microsecond=0)
            else:
                date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

        return date_from

    @cached_property
    def _now(self):
        return self._localize_to_team(timezone.now())

    def _localize_to_team(self, target: datetime):
        return target.astimezone(pytz.timezone(self._team.timezone))

    @cached_property
    def interval_annotation(self) -> str:
        period = self._filter.interval if isinstance(self._filter, IntervalMixin) else None
        if period is None:
            period = "day"
        ch_function = PERIOD_TO_TRUNC_FUNC.get(period.lower())
        if ch_function is None:
            raise ValidationError(f"Period {period} is unsupported.")
        return ch_function

    @cached_property
    def date_to_clause(self):
        return self._get_timezone_aware_date_condition("date_to")

    @cached_property
    def date_from_clause(self):
        return self._get_timezone_aware_date_condition("date_from")

    @cached_property
    def date_to(self) -> Tuple[str, Dict]:
        date_to_query = self.date_to_clause
        date_to = self.date_to_param

        date_to_param = {"date_to": date_to.strftime("%Y-%m-%d %H:%M:%S"), "timezone": self._team.timezone}

        return date_to_query, date_to_param

    @cached_property
    def date_from(self) -> Tuple[str, Dict]:
        date_from_query = self.date_from_clause
        date_from = self.date_from_param

        date_from_param = {"date_from": date_from.strftime("%Y-%m-%d %H:%M:%S"), "timezone": self._team.timezone}

        return date_from_query, date_from_param

    def _get_timezone_aware_date_condition(self, date_param: Literal["date_from", "date_to"]) -> str:
        operator = ">=" if date_param == "date_from" else "<="
        event_timestamp_expr = self._normalize_datetime(column=f"{self._table}timestamp")
        date_expr = self._normalize_datetime(param=date_param)
        if operator == ">=" and self.should_round:  # Round date_from to start of interval if `should_round` is true
            date_expr = self._truncate_normalized_datetime(date_expr, self.interval_annotation)
        return f"AND {event_timestamp_expr} {operator} {date_expr}"

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
    def _start_time(self) -> datetime:
        return self._filter.date_from or get_earliest_timestamp(self._team.pk)

    @cached_property
    def _end_time(self) -> datetime:
        return self._filter.date_to or timezone.now()

    @cached_property
    def time_difference(self) -> timedelta:
        return self._end_time - self._start_time

    @cached_property
    def num_intervals(self) -> int:
        if not isinstance(self._filter, IntervalMixin):
            return 1
        if self._filter.interval == "month":
            rel_delta = relativedelta(self._end_time.replace(day=1), self._start_time.replace(day=1))
            return (rel_delta.years * 12) + rel_delta.months + 1

        return int(self.time_difference.total_seconds() / TIME_IN_SECONDS[self._filter.interval]) + 1

    @cached_property
    def should_round(self) -> bool:
        if self._should_round is not None:
            return self._should_round

        if not isinstance(self._filter, IntervalMixin) or self._filter.use_explicit_dates:
            return False

        round_interval = False
        if self._filter.interval in ["week", "month"]:
            round_interval = True
        else:
            round_interval = self.time_difference.total_seconds() >= TIME_IN_SECONDS[self._filter.interval] * 2

        return round_interval

    def _is_hourly(self, delta_mapping: Optional[Dict[str, int]]):
        if not isinstance(self._filter, IntervalMixin):
            return False
        return self._filter.interval == "hour" or (delta_mapping and "hours" in delta_mapping)
