from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.models.filters import Filter


def parse_timestamps(filter: Filter, team_id: int, table: str = "") -> Tuple[str, str, dict]:
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
    is_hour_or_min = (filter.interval and filter.interval.lower() == "hour") or (
        filter.interval and filter.interval.lower() == "minute"
    )
    return timestamp.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if is_hour_or_min else default_hour_min))


def get_earliest_timestamp(team_id: int) -> datetime:
    return sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id})[0][0]


def get_time_diff(
    interval: str, start_time: Optional[datetime], end_time: Optional[datetime], team_id: int
) -> Tuple[int, int]:

    _start_time = start_time or get_earliest_timestamp(team_id)
    _end_time = end_time or timezone.now()

    time_diffs: Dict[str, Any] = {
        "minute": 60,
        "hour": 3600,
        "day": 3600 * 24,
        "week": 3600 * 24 * 7,
        "month": 3600 * 24 * 30,
    }

    diff = _end_time - _start_time
    return int(diff.total_seconds() / time_diffs[interval]) + 1, time_diffs[interval]


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
