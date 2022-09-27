import json
from datetime import datetime
from typing import Any, Dict, Optional

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.client import sync_execute
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA

EARLIEST_TIMESTAMP = "2015-01-01"

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s AND timestamp > %(earliest_timestamp)s order by timestamp limit 1
"""

TIME_IN_SECONDS: Dict[str, Any] = {
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,  # TODO: Let's get rid of this lie! Months are not all 30 days long
}

PERIOD_TO_TRUNC_FUNC: Dict[str, str] = {
    "hour": "toStartOfHour",
    "week": "toStartOfWeek",
    "day": "toStartOfDay",
    "month": "toStartOfMonth",
}

PERIOD_TO_INTERVAL_FUNC: Dict[str, str] = {
    "hour": "toIntervalHour",
    "week": "toIntervalWeek",
    "day": "toIntervalDay",
    "month": "toIntervalMonth",
}


def get_earliest_timestamp(team_id: int) -> datetime:
    results = sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id, "earliest_timestamp": EARLIEST_TIMESTAMP})
    if len(results) > 0:
        return results[0][0]
    else:
        return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA


def get_trunc_func_ch(period: Optional[str]) -> str:
    if period is None:
        period = "day"
    ch_function = PERIOD_TO_TRUNC_FUNC.get(period.lower())
    if ch_function is None:
        raise ValidationError(f"Period {period} is unsupported.")
    return ch_function


def get_interval_func_ch(period: Optional[str]) -> str:
    if period is None:
        period = "day"
    ch_function = PERIOD_TO_INTERVAL_FUNC.get(period.lower())
    if ch_function is None:
        raise ValidationError(f"Interval {period} is unsupported.")
    return ch_function


def deep_dump_object(params: Dict[str, Any]) -> Dict[str, Any]:
    for key in params:
        if isinstance(params[key], dict) or isinstance(params[key], list):
            params[key] = json.dumps(params[key])
    return params


def start_of_week_fix(interval: Optional[str]) -> str:
    """
    toStartOfWeek is the only trunc function that takes three arguments:
      toStartOfWeek(timestamp, mode, timezone)
    Mode is whether the week starts on sunday or monday, with 0 being sunday.
    This function adds mode to the trunc_func, but only if the interval is week
    """
    return ", 0" if interval and interval.lower() == "week" else ""


def convert_to_datetime_aware(date_obj):
    if date_obj.tzinfo is None:
        date_obj = date_obj.replace(tzinfo=timezone.utc)
    return date_obj
