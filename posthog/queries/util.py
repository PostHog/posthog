import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pytz
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.cache_utils import cache_for
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.queries.insight import insight_sync_execute

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

# TODO: refactor since this is only used in one spot now
def format_ch_timestamp(timestamp: datetime, convert_to_timezone: Optional[str] = None):
    if convert_to_timezone:
        # Here we probably get a timestamp set to the beginning of the day (00:00), in UTC
        # We need to convert that UTC timestamp to the local timestamp (00:00 in US/Pacific for example)
        # Then we convert it back to UTC (08:00 in UTC)
        if timestamp.tzinfo and timestamp.tzinfo != pytz.UTC:
            raise ValidationError(detail="You must pass a timestamp with no timezone or UTC")
        timestamp = pytz.timezone(convert_to_timezone).localize(timestamp.replace(tzinfo=None)).astimezone(pytz.UTC)

    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


@cache_for(timedelta(seconds=2))
def get_earliest_timestamp(team_id: int) -> datetime:
    results = insight_sync_execute(
        GET_EARLIEST_TIMESTAMP_SQL,
        {"team_id": team_id, "earliest_timestamp": EARLIEST_TIMESTAMP},
        query_type="get_earliest_timestamp",
    )
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


def get_time_in_seconds_for_period(period: Optional[str]) -> str:
    if period is None:
        period = "day"
    seconds_in_period = TIME_IN_SECONDS.get(period.lower())
    if seconds_in_period is None:
        raise ValidationError(f"Interval {period} is unsupported.")
    return seconds_in_period


def deep_dump_object(params: Dict[str, Any]) -> Dict[str, Any]:
    for key in params:
        if isinstance(params[key], dict) or isinstance(params[key], list):
            params[key] = json.dumps(params[key])
    return params


def convert_to_datetime_aware(date_obj):
    if date_obj.tzinfo is None:
        date_obj = date_obj.replace(tzinfo=timezone.utc)
    return date_obj


def correct_result_for_sampling(value: int, sampling_factor: Optional[float], entity_math: Optional[str] = None) -> int:
    from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS

    # We don't adjust results for sampling if:
    # - There's no sampling_factor specified i.e. the query isn't sampled
    # - The query performs a math operation other than 'sum' because statistical math operations
    # on sampled data yield results in the correct format
    if (not sampling_factor) or (
        entity_math is not None and entity_math != "sum" and entity_math in ALL_SUPPORTED_MATH_FUNCTIONS
    ):
        return value

    result: int = round(value * (1 / sampling_factor))
    return result
