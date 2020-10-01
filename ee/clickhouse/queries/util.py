from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.models.filter import Filter


def parse_timestamps(filter: Filter) -> Tuple[Optional[str], Optional[str]]:
    date_from = None
    date_to = None

    if filter._date_from and filter.date_from:
        date_from = "and timestamp >= '{}'".format(
            filter.date_from.strftime(
                "%Y-%m-%d{}".format(
                    " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                )
            )
        )
    else:
        try:
            earliest_date = sync_execute(GET_EARLIEST_TIMESTAMP_SQL)[0][0]
        except IndexError:
            date_from = ""
        else:
            date_from = "and timestamp >= '{}'".format(
                earliest_date.strftime(
                    "%Y-%m-%d{}".format(
                        " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                    )
                )
            )

    if filter.date_to:
        _date_to = filter.date_to
    else:
        _date_to = timezone.now()

    date_to = "and timestamp <= '{}'".format(
        _date_to.strftime(
            "%Y-%m-%d{}".format(
                " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 23:59:59"
            )
        )
    )
    return date_from, date_to


def get_time_diff(interval: str, start_time: Optional[datetime], end_time: Optional[datetime]) -> Tuple[int, int]:

    _start_time = start_time or sync_execute(GET_EARLIEST_TIMESTAMP_SQL)[0][0]
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


def get_interval_annotation_ch(interval: Optional[str]) -> str:
    if interval is None:
        return "toStartOfDay"

    map: Dict[str, str] = {
        "minute": "toStartOfMinute",
        "hour": "toStartOfHour",
        "day": "toStartOfDay",
        "week": "toStartOfWeek",
        "month": "toStartOfMonth",
    }
    return map[interval]
