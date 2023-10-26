import json
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, Optional, Union

from zoneinfo import ZoneInfo
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.cache_utils import cache_for
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.team import Team
from posthog.models.team.team import WeekStartDay
from posthog.queries.insight import insight_sync_execute
from posthog.utils import PersonOnEventsMode


class PersonPropertiesMode(Enum):
    USING_SUBQUERY = auto()
    USING_PERSON_PROPERTIES_COLUMN = auto()
    # Used for generating query on Person table
    DIRECT = auto()
    """Get person property from the persons table, selecting the latest version of the person."""
    DIRECT_ON_PERSONS = auto()
    """
    Get person property from the persons table WITHOUT aggregation by version. Not fully accurate, as old versions
    of the person will be matched, but useful for prefiltering on whether _any_ version of the person has ever matched.
    That's a good way of eliminating most persons early on in the query pipeline, which can greatly reduce the overall
    memory usage of a query (as aggregation by version happens in-memory).
    """
    DIRECT_ON_EVENTS = auto()
    """
    Get person property from the events table (persons-on-events v1 - no person ID overrides),
    selecting the latest version of the person.
    """
    DIRECT_ON_EVENTS_WITH_POE_V2 = auto()
    """
    Get person property from the events table (persons-on-events v2 - accounting for person ID overrides),
    selecting the latest version of the person.
    """


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
        if timestamp.tzinfo and timestamp.tzinfo != ZoneInfo("UTC"):
            raise ValidationError(detail="You must pass a timestamp with no timezone or UTC")
        timestamp = timestamp.replace(tzinfo=ZoneInfo(convert_to_timezone)).astimezone(ZoneInfo("UTC"))
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


@cache_for(timedelta(seconds=2))
def get_earliest_timestamp(team_id: int) -> datetime:
    results = insight_sync_execute(
        GET_EARLIEST_TIMESTAMP_SQL,
        {"team_id": team_id, "earliest_timestamp": EARLIEST_TIMESTAMP},
        query_type="get_earliest_timestamp",
        team_id=team_id,
    )
    if len(results) > 0:
        return results[0][0]
    else:
        return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA


def get_start_of_interval_sql(
    interval: str,
    *,
    team: Team,
    source: str = "timestamp",
    ensure_datetime: bool = False,
) -> str:
    trunc_func = get_trunc_func_ch(interval)
    if source.startswith("%(") and source.endswith(")s"):
        source = f"toDateTime({source}, %(timezone)s)"
    elif "%(timezone)s" not in source:
        source = f"toTimeZone(toDateTime({source}, 'UTC'), %(timezone)s)"
    trunc_func_args = [source]
    if interval == "week":
        trunc_func_args.append((WeekStartDay(team.week_start_day or 0)).clickhouse_mode)
    interval_sql = f"{trunc_func}({', '.join(trunc_func_args)})"
    # For larger intervals dates are returned instead of datetimes, and we always want datetimes for comparisons
    return f"toDateTime({interval_sql}, %(timezone)s)" if ensure_datetime else interval_sql


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


def correct_result_for_sampling(
    value: Union[int, float],
    sampling_factor: Optional[float],
    entity_math: Optional[str] = None,
) -> Union[int, float]:
    from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS

    # We don't adjust results for sampling if:
    # - There's no sampling_factor specified i.e. the query isn't sampled
    # - The query performs a math operation other than 'sum' because statistical math operations
    # on sampled data yield results in the correct format
    if (not sampling_factor) or (
        entity_math is not None and entity_math != "sum" and entity_math in ALL_SUPPORTED_MATH_FUNCTIONS
    ):
        return value

    result = round(value * (1 / sampling_factor))
    return result


def get_person_properties_mode(team: Team) -> PersonPropertiesMode:
    if team.person_on_events_mode == PersonOnEventsMode.DISABLED:
        return PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN

    if team.person_on_events_mode == PersonOnEventsMode.V2_ENABLED:
        return PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2

    return PersonPropertiesMode.DIRECT_ON_EVENTS
