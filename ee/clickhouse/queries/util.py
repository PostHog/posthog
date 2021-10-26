from datetime import datetime
from typing import Dict, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.filters.sessions_filter import SessionEventsFilter
from posthog.queries.base import TIME_IN_SECONDS
from posthog.types import FilterType


def parse_timestamps(
    filter: Union[FilterType, SessionEventsFilter], team_id: int, table: str = ""
) -> Tuple[str, str, dict]:
    date_from = None
    date_to = None
    params = {}
    if filter.date_from:

        date_from = f"AND {table}timestamp >= %(date_from)s"
        params.update({"date_from": format_ch_timestamp(filter.date_from, filter)})
    else:
        try:
            earliest_date = get_earliest_timestamp(team_id)
        except IndexError:
            date_from = ""
        else:
            date_from = f"AND {table}timestamp >= %(date_from)s"
            params.update({"date_from": format_ch_timestamp(earliest_date, filter)})

    _date_to = filter.date_to

    date_to = f"AND {table}timestamp <= %(date_to)s"
    params.update({"date_to": format_ch_timestamp(_date_to, filter, " 23:59:59")})

    return date_from or "", date_to or "", params


def format_ch_timestamp(timestamp: datetime, filter, default_hour_min: str = " 00:00:00"):
    is_hour_or_min = (
        (filter.interval and filter.interval.lower() == "hour")
        or (filter.interval and filter.interval.lower() == "minute")
        or (filter._date_from == "-24h")
        or (filter._date_from == "-48h")
    )
    return timestamp.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if is_hour_or_min else default_hour_min))


def get_earliest_timestamp(team_id: int) -> datetime:
    results = sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id})
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
    "minute": "toStartOfMinute",
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
    "minute": "toIntervalMinute",
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
        return "AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s))".format(interval=interval_annotation)
    else:
        return "AND timestamp >= %(date_from)s"
