import json
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any, Optional, Union, overload
from zoneinfo import ZoneInfo

from django.utils import timezone

from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.schema import PersonsOnEventsMode

from posthog.cache_utils import cache_for
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.models.team.team import Team, WeekStartDay
from posthog.queries.insight import insight_sync_execute


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


@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode) -> PersonsOnEventsMode: ...
@overload
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None: ...
def alias_poe_mode_for_legacy(persons_on_events_mode: PersonsOnEventsMode | None) -> PersonsOnEventsMode | None:
    if persons_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
        # PERSON_ID_OVERRIDE_PROPERTIES_JOINED is not implemented in legacy insights
        # It's functionally the same as DISABLED, just slower - hence aliasing to DISABLED
        return PersonsOnEventsMode.DISABLED
    return persons_on_events_mode


EARLIEST_TIMESTAMP = "2015-01-01"

# Lower bound below which timestamps are treated as corrupt/invalid and ignored.
EARLIEST_TIMESTAMP_DATETIME = datetime(2015, 1, 1, tzinfo=UTC)

# Probe for the earliest event of a team with a *bounded* `min(timestamp)` rather than an
# open-ended `ORDER BY timestamp LIMIT 1`. The events table sort key is
# `(team_id, toDate(timestamp), ...)` and it carries a minmax skip index on `timestamp`, so a
# query constrained to a narrow `[lower, upper)` window only reads the granules inside that window.
# An unbounded `ORDER BY timestamp LIMIT 1` cannot short-circuit on a Distributed ReplacingMergeTree
# and ends up scanning the whole team, so we instead walk an exponentially widening window from the
# floor and stop at the first window that contains data — `min` over `[floor, upper)` is exactly the
# global earliest once that window is non-empty.
GET_EARLIEST_TIMESTAMP_BOUNDED_SQL = """
SELECT min(timestamp) FROM events
WHERE team_id = %(team_id)s AND timestamp > %(earliest_timestamp)s AND timestamp < %(upper_bound)s
"""

TIME_IN_SECONDS: dict[str, Any] = {
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,  # TODO: Let's get rid of this lie! Months are not all 30 days long
}

PERIOD_TO_TRUNC_FUNC: dict[str, str] = {
    "hour": "toStartOfHour",
    "week": "toStartOfWeek",
    "day": "toStartOfDay",
    "month": "toStartOfMonth",
}

PERIOD_TO_INTERVAL_FUNC: dict[str, str] = {
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


def _earliest_timestamp_upper_bounds(now: datetime) -> list[datetime]:
    """Ascending upper bounds for the widening-window earliest-event probe.

    Each bound is a literal (constant-folded) datetime so ClickHouse can prune partitions and
    skip-index granules — only the granules inside `[floor, upper)` get read. We want the windows
    to be narrow wherever a team's first event is likely to fall:

    - Two short windows just above the floor catch the very common case of legacy/corrupt events
      clustered at the epoch floor, resolving those teams in a single cheap probe.
    - Windows at `now - 2**k` months give progressively finer resolution toward the present, where
      most teams' genuine first event lands. This keeps the first non-empty window tight even for
      teams whose data only starts recently.

    The final bound is strictly after `now`, so the last probe always covers every event a team
    could have (and an empty result there means the team has no events).
    """
    final_bound = now + relativedelta(days=1)
    candidates: set[datetime] = {
        EARLIEST_TIMESTAMP_DATETIME + relativedelta(months=1),
        EARLIEST_TIMESTAMP_DATETIME + relativedelta(months=3),
        final_bound,
    }
    months = 1
    while now - relativedelta(months=months) > EARLIEST_TIMESTAMP_DATETIME:
        candidates.add(now - relativedelta(months=months))
        months *= 2
    return sorted(bound for bound in candidates if EARLIEST_TIMESTAMP_DATETIME < bound <= final_bound)


@cache_for(timedelta(seconds=2))
def get_earliest_timestamp(team_id: int) -> datetime:
    for upper_bound in _earliest_timestamp_upper_bounds(timezone.now()):
        results = insight_sync_execute(
            GET_EARLIEST_TIMESTAMP_BOUNDED_SQL,
            {
                "team_id": team_id,
                "earliest_timestamp": EARLIEST_TIMESTAMP,
                "upper_bound": upper_bound.strftime("%Y-%m-%d %H:%M:%S"),
            },
            query_type="get_earliest_timestamp",
            team_id=team_id,
        )
        # `min` over an empty window returns the DateTime epoch (1970), which is below the floor.
        # Any genuine result is strictly after the floor, so the first such value is the earliest event.
        if (
            results
            and results[0][0] is not None
            and convert_to_datetime_aware(results[0][0]) > EARLIEST_TIMESTAMP_DATETIME
        ):
            return results[0][0]

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
    if trunc_func == "toStartOfWeek":
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


def deep_dump_object(params: dict[str, Any]) -> dict[str, Any]:
    for key in params:
        if isinstance(params[key], dict) or isinstance(params[key], list):
            params[key] = json.dumps(params[key])
    return params


def convert_to_datetime_aware(date_obj):
    if date_obj.tzinfo is None:
        date_obj = date_obj.replace(tzinfo=UTC)
    return date_obj


def correct_result_for_sampling(
    value: Union[int, float],
    sampling_factor: Optional[float],
    entity_math: Optional[str] = None,
) -> Union[int, float]:
    from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS

    # We don't adjust results for sampling if:
    # - There's no sampling_factor specified i.e. the query isn't sampled
    # - The value is not a number (should not happen, but being defensive, especially against HogQL aggregation)
    # - The query performs a math operation other than 'sum' because statistical math operations
    # on sampled data yield results in the correct format
    if (
        not sampling_factor
        or not isinstance(value, int | float)
        or (entity_math is not None and entity_math != "sum" and entity_math in ALL_SUPPORTED_MATH_FUNCTIONS)
    ):
        return value

    result = round(value * (1 / sampling_factor))
    return result


def get_person_properties_mode(team: Team) -> PersonPropertiesMode:
    if team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
        return PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2
    if team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
        return PersonPropertiesMode.DIRECT_ON_EVENTS
    return PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN
