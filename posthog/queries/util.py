import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pytz
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.client import sync_execute
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import TIME_IN_SECONDS
from posthog.types import FilterType

EARLIEST_TIMESTAMP = "2015-01-01"

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s AND timestamp > %(earliest_timestamp)s order by timestamp limit 1
"""


def parse_timestamps(filter: FilterType, team: Team, table: str = "") -> Tuple[str, str, dict]:
    date_from = None
    date_to = None
    params = {}
    if filter.date_from:
        date_from = f"AND {table}timestamp >= toDateTime(%(date_from)s)"
        params.update(
            {
                "date_from": format_ch_timestamp(
                    filter.date_from,
                    convert_to_timezone=team.timezone if not filter.date_from_has_explicit_time else None,
                )
            }
        )
    else:
        try:
            earliest_date = get_earliest_timestamp(team.pk)
        except IndexError:
            date_from = ""
        else:
            date_from = f"AND {table}timestamp >= toDateTime(%(date_from)s)"
            params.update({"date_from": format_ch_timestamp(earliest_date)})

    _date_to = filter.date_to

    date_to = f"AND {table}timestamp <= toDateTime(%(date_to)s)"
    params.update(
        {
            "date_to": format_ch_timestamp(
                _date_to,
                convert_to_timezone=team.timezone if filter._date_to and not filter.date_to_has_explicit_time else None,
            )
        }
    )

    return date_from or "", date_to or "", params


def format_ch_timestamp(timestamp: datetime, convert_to_timezone: Optional[str] = None):
    if convert_to_timezone:
        # Here we probably get a timestamp set to the beginning of the day (00:00), in UTC
        # We need to convert that UTC timestamp to the local timestamp (00:00 in US/Pacific for example)
        # Then we convert it back to UTC (08:00 in UTC)
        if timestamp.tzinfo and timestamp.tzinfo != pytz.UTC:
            raise ValidationError(detail="You must pass a timestamp with no timezone or UTC")
        timestamp = pytz.timezone(convert_to_timezone).localize(timestamp.replace(tzinfo=None)).astimezone(pytz.UTC)

    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def get_earliest_timestamp(team_id: int) -> datetime:
    results = sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id, "earliest_timestamp": EARLIEST_TIMESTAMP})
    if len(results) > 0:
        return results[0][0]
    else:
        return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA


def get_time_diff(
    interval: str, start_time: Optional[datetime], end_time: Optional[datetime], team_id: int
) -> Tuple[int, int, bool]:

    _start_time = start_time or get_earliest_timestamp(team_id)
    _end_time = end_time or timezone.now()

    if interval == "month":
        rel_delta = relativedelta(_end_time.replace(day=1), _start_time.replace(day=1))
        return (rel_delta.years * 12) + rel_delta.months + 1, TIME_IN_SECONDS["month"], True

    diff = _end_time - _start_time
    if interval == "week":
        round_interval = True
    else:
        round_interval = diff.total_seconds() >= TIME_IN_SECONDS[interval] * 2

    return (
        # NOTE: `int` will simply strip the decimal part. Checking the
        # extremities, if start_time, end_time are less than an interval apart,
        # we'll get 0, then add 1, so we'll always get at least one interval
        int(diff.total_seconds() / TIME_IN_SECONDS[interval]) + 1,
        TIME_IN_SECONDS[interval],
        round_interval,
    )


PERIOD_TO_TRUNC_FUNC: Dict[str, str] = {
    "hour": "toStartOfHour",
    "week": "toStartOfWeek",
    "day": "toStartOfDay",
    "month": "toStartOfMonth",
}


def get_trunc_func_ch(period: Optional[str]) -> str:
    if period is None:
        period = "day"
    ch_function = PERIOD_TO_TRUNC_FUNC.get(period.lower())
    if ch_function is None:
        raise ValidationError(f"Period {period} is unsupported.")
    return ch_function


PERIOD_TO_INTERVAL_FUNC: Dict[str, str] = {
    "hour": "toIntervalHour",
    "week": "toIntervalWeek",
    "day": "toIntervalDay",
    "month": "toIntervalMonth",
}


def get_interval_func_ch(period: Optional[str]) -> str:
    if period is None:
        period = "day"
    ch_function = PERIOD_TO_INTERVAL_FUNC.get(period.lower())
    if ch_function is None:
        raise ValidationError(f"Interval {period} is unsupported.")
    return ch_function


def date_from_clause(interval_annotation: str, round_interval: bool) -> str:
    if round_interval:
        # Truncate function in clickhouse will remove the time granularity and leave only the date
        # Specify that this truncated date is the local timezone target
        # Convert target to UTC so that stored timestamps can be compared accordingly
        # Example: `2022-04-05 07:00:00` -> truncated to `2022-04-05` -> 2022-04-05 00:00:00 PST -> 2022-04-05 07:00:00 UTC
        if interval_annotation == "toStartOfWeek":
            return "AND timestamp >= toTimezone(toDateTime(toStartOfWeek(toDateTime(%(date_from)s), 0), %(timezone)s), 'UTC')"

        return "AND timestamp >= toTimezone(toDateTime({interval}(toDateTime(%(date_from)s)), %(timezone)s), 'UTC')".format(
            interval=interval_annotation
        )
    else:
        return "AND timestamp >= toDateTime(%(date_from)s)"


def deep_dump_object(params: Dict[str, Any]) -> Dict[str, Any]:
    for key in params:
        if isinstance(params[key], dict) or isinstance(params[key], list):
            params[key] = json.dumps(params[key])
    return params


def start_of_week_fix(filter: Filter) -> str:
    """
    toStartOfWeek is the only trunc function that takes three arguments:
      toStartOfWeek(timestamp, mode, timezone)
    Mode is whether the week starts on sunday or monday, with 0 being sunday.
    This function adds mode to the trunc_func, but only if the interval is week
    """
    return "0," if filter.interval == "week" else ""
