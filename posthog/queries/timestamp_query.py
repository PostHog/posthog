from datetime import timedelta
from functools import cached_property
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.models.team import Team
from posthog.queries.util import format_ch_timestamp, get_earliest_timestamp


class TimestampQuery:
    def __init__(self, filter, team: Team, table="") -> None:
        self._filter = filter
        self._team = team
        self._table = f"{table}." if table else ""

    @cached_property
    def date_to_param(self) -> Optional[str]:
        return self._date_param(self._filter.date_to, self._filter.date_to_has_explicit_time)

    def _date_param(self, target_date, has_explicit_time) -> str:
        return format_ch_timestamp(
            target_date,
            convert_to_timezone=self._team.timezone if not has_explicit_time else None,
        )

    @cached_property
    def interval_annotation(self) -> str:
        period = self._filter.interval
        if period is None:
            period = "day"
        ch_function = PERIOD_TO_TRUNC_FUNC.get(period.lower())
        if ch_function is None:
            raise ValidationError(f"Period {period} is unsupported.")
        return ch_function

    @cached_property
    def date_to_clause(self):
        return f"AND {self._table}timestamp <= toDateTime(%(date_to)s)"

    @cached_property
    def date_from_clause(self):
        return self._get_timezone_aware_date_condition(">=", "date_from")

    @cached_property
    def date_to(self) -> Tuple[str, Dict]:
        date_to_query = self.date_to_clause
        date_to_param = {"date_to": self.date_to_param}

        return date_to_query, date_to_param

    @cached_property
    def date_from(self) -> Tuple[str, Dict]:
        date_from_query = self.date_from_clause
        date_from_param = {}
        if self._filter.date_from:
            date_from_query = self.date_from_clause
            date_from_param.update(
                {"date_from": self._date_param(self._filter.date_from, self._filter.date_from_has_explicit_time)}
            )
        else:
            try:
                earliest_date = get_earliest_timestamp(self._team.pk)
            except IndexError:
                date_from_query = ""
            else:
                date_from_query = self.date_from_clause
                date_from_param.update(
                    {"date_from": self._date_param(earliest_date, self._filter.date_from_has_explicit_time)}
                )

        return date_from_query, date_from_param

    def _get_timezone_aware_date_condition(self, operator: str, date_clause: str) -> str:
        if self.should_round:
            # Truncate function in clickhouse will remove the time granularity and leave only the date
            # Specify that this truncated date is the local timezone target
            # Convert target to UTC so that stored timestamps can be compared accordingly
            # Example: `2022-04-05 07:00:00` -> truncated to `2022-04-05` -> 2022-04-05 00:00:00 PST -> 2022-04-05 07:00:00 UTC

            return f"AND {self._table}timestamp {operator} {self._timezone_date_clause(date_clause)}"
        else:
            return f"AND {self._table}timestamp {operator} toDateTime(%({date_clause})s)"

    def _timezone_date_clause(self, date_clause: str) -> str:
        clause = (
            f"toTimezone(toDateTime({self.interval_annotation}(toDateTime(%({date_clause})s)), %(timezone)s), 'UTC')"
        )

        if self.interval_annotation == "toStartOfWeek":
            return f"toTimezone(toDateTime(toStartOfWeek(toDateTime(%({date_clause})s), 0), %(timezone)s), 'UTC')"

        return clause

    @cached_property
    def time_difference(self) -> timedelta:
        _start_time = self._filter.date_from or get_earliest_timestamp(self._team.pk)
        _end_time = self._filter.date_to or timezone.now()

        return _end_time - _start_time

    @cached_property
    def num_intervals(self):
        return (int(self.time_difference.total_seconds() / TIME_IN_SECONDS[self._filter.interval]) + 1,)

    @cached_property
    def should_round(self):
        round_interval = False
        if self._filter.interval == "week":
            round_interval = True
        else:
            round_interval = self.time_difference.total_seconds() >= TIME_IN_SECONDS[self._filter.interval] * 2

        return round_interval


PERIOD_TO_TRUNC_FUNC: Dict[str, str] = {
    "hour": "toStartOfHour",
    "week": "toStartOfWeek",
    "day": "toStartOfDay",
    "month": "toStartOfMonth",
}

TIME_IN_SECONDS: Dict[str, Any] = {
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,  # TODO: Let's get rid of this lie! Months are not all 30 days long
}
