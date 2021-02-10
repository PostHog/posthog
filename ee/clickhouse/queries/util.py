from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Union

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.models.filters import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.queries.base import TIME_IN_SECONDS
from posthog.types import FilterType


def parse_timestamps(filter: FilterType, team_id: int, table: str = "") -> Tuple[str, str, dict]:
    date_from = None
    date_to = None
    params = {}
    if filter.date_from:
        date_from = "and {table}timestamp >= '{}'".format(format_ch_timestamp(filter.date_from, filter), table=table,)
        params.update({"date_from": format_ch_timestamp(filter.date_from, filter)})
    else:
        try:
            earliest_date = get_earliest_timestamp(team_id)
        except IndexError:
            date_from = ""
        else:
            date_from = "and {table}timestamp >= '{}'".format(format_ch_timestamp(earliest_date, filter), table=table,)
            params.update({"date_from": format_ch_timestamp(earliest_date, filter)})

    _date_to = filter.date_to

    date_to = "and {table}timestamp <= '{}'".format(format_ch_timestamp(_date_to, filter, " 23:59:59"), table=table,)
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
    return sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id})[0][0]


def get_time_diff(
    interval: str, start_time: Optional[datetime], end_time: Optional[datetime], team_id: int
) -> Tuple[int, int, bool]:

    _start_time = start_time or get_earliest_timestamp(team_id)
    _end_time = end_time or timezone.now()

    diff = _end_time - _start_time
    round_interval = diff.total_seconds() >= TIME_IN_SECONDS[interval] * 2

    return int(diff.total_seconds() / TIME_IN_SECONDS[interval]) + 1, TIME_IN_SECONDS[interval], round_interval


PERIOD_TRUNC_MINUTE = "toStartOfMinute"
PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


def get_trunc_func_ch(period: Optional[str]) -> str:
    if period is None:
        return PERIOD_TRUNC_DAY

    period = period.lower()
    if period == "minute":
        return PERIOD_TRUNC_MINUTE
    elif period == "hour":
        return PERIOD_TRUNC_HOUR
    elif period == "week":
        return PERIOD_TRUNC_WEEK
    elif period == "day":
        return PERIOD_TRUNC_DAY
    elif period == "month":
        return PERIOD_TRUNC_MONTH
    else:
        raise ValueError(f"Period {period} is unsupported.")


def date_from_clause(interval_annotation: str, round_interval: bool) -> str:
    if round_interval:
        return "AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s))".format(interval=interval_annotation)
    else:
        return "AND timestamp >= %(date_from)s"
