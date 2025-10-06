import datetime
from datetime import timedelta
from typing import Any, Optional, TypeVar
from zoneinfo import ZoneInfo

import structlog
from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.schema import PersonsOnEventsMode

from posthog.hogql.hogql import translate_hogql

from posthog.constants import MONTHLY_ACTIVE, NON_TIME_SERIES_DISPLAY_TYPES, UNIQUE_GROUPS, UNIQUE_USERS, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.event.sql import EVENT_JOIN_PERSON_SQL
from posthog.models.filters import Filter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp

logger = structlog.get_logger(__name__)

PROPERTY_MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p75": "quantile(0.75)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}

COUNT_PER_ACTOR_MATH_FUNCTIONS = {
    "avg_count_per_actor": "avg",
    "min_count_per_actor": "min",
    "max_count_per_actor": "max",
    "median_count_per_actor": "quantile(0.50)",
    "p75_count_per_actor": "quantile(0.75)",
    "p90_count_per_actor": "quantile(0.90)",
    "p95_count_per_actor": "quantile(0.95)",
    "p99_count_per_actor": "quantile(0.99)",
}

ALL_SUPPORTED_MATH_FUNCTIONS = [
    *list(PROPERTY_MATH_FUNCTIONS.keys()),
    *list(COUNT_PER_ACTOR_MATH_FUNCTIONS.keys()),
]


def process_math(
    entity: Entity,
    team: Team,
    filter: Filter,
    event_table_alias: Optional[str] = None,
    person_id_alias: str = "person_id",
) -> tuple[str, str, dict[str, Any]]:
    aggregate_operation = "count(*)"
    join_condition = ""
    params: dict[str, Any] = {}

    if entity.math in (UNIQUE_USERS, WEEKLY_ACTIVE, MONTHLY_ACTIVE):
        if team.aggregate_users_by_distinct_id:
            join_condition = ""
            aggregate_operation = f"count(DISTINCT {event_table_alias + '.' if event_table_alias else ''}distinct_id)"
        else:
            join_condition = EVENT_JOIN_PERSON_SQL
            aggregate_operation = f"count(DISTINCT {person_id_alias})"
    elif entity.math == "unique_group":
        validate_group_type_index("math_group_type_index", entity.math_group_type_index, required=True)

        aggregate_operation = f'count(DISTINCT "$group_{entity.math_group_type_index}")'
    elif entity.math == "unique_session":
        aggregate_operation = f"count(DISTINCT {event_table_alias + '.' if event_table_alias else ''}\"$session_id\")"
    elif entity.math in PROPERTY_MATH_FUNCTIONS:
        if entity.math_property is None:
            raise ValidationError(
                {"math_property": "This field is required when `math` is set to a function."},
                code="required",
            )
        if entity.math_property == "$session_duration":
            aggregate_operation = f"{PROPERTY_MATH_FUNCTIONS[entity.math]}(session_duration)"
        else:
            key = f"e_{entity.index}_math_prop"
            value, _ = get_property_string_expr("events", entity.math_property, f"%({key})s", "properties")
            aggregate_operation = f"{PROPERTY_MATH_FUNCTIONS[entity.math]}(toFloat64OrNull({value}))"
            params[key] = entity.math_property
    elif entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
        aggregate_operation = f"{COUNT_PER_ACTOR_MATH_FUNCTIONS[entity.math]}(intermediate_count)"
    elif entity.math == "hogql":
        aggregate_operation = translate_hogql(entity.math_hogql, filter.hogql_context)

    return aggregate_operation, join_condition, params


def parse_response(
    stats: dict,
    filter: Filter,
    additional_values: Optional[dict] = None,
    entity: Optional[Entity] = None,
) -> dict[str, Any]:
    if additional_values is None:
        additional_values = {}
    counts = stats[1]
    labels = [item.strftime("%-d-%b-%Y{}".format(" %H:%M" if filter.interval == "hour" else "")) for item in stats[0]]
    days = [item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")) for item in stats[0]]

    entity_math = entity.math if entity is not None else None
    counts = [correct_result_for_sampling(c, filter.sampling_factor, entity_math) for c in counts]
    return {
        "data": [float(c) for c in counts],
        "count": float(sum(counts)),
        "labels": labels,
        "days": days,
        **additional_values,
    }


def get_active_user_params(filter: Filter, entity: Entity, team_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    diff = timedelta(days=7 if entity.math == WEEKLY_ACTIVE else 30)

    date_from: datetime.datetime
    if filter.date_from:
        date_from = filter.date_from
    else:
        try:
            date_from = get_earliest_timestamp(team_id)
        except IndexError:
            raise ValidationError("Active User queries require a lower date bound")
    date_to = filter.date_to

    format_params = {
        "prev_interval": "6 DAY" if entity.math == WEEKLY_ACTIVE else "29 DAY",
        "parsed_date_from_prev_range": f"AND toDateTime(timestamp, 'UTC') >= toDateTime(%(date_from_active_users_adjusted)s, %(timezone)s)",
    }

    # For time-series display types, we need to adjust date_from to be 7/30 days earlier.
    # This is because each data point effectively has its own range, which starts 6/29 days before its date marker,
    # and ends on that particular date marker.
    # In case of aggregate display modes (NON_TIME_SERIES_DISPLAY_TYPES), the query is much simpler – with only one
    # global range – and is basically distinct persons who have an event in the 7/30 days before date_to.
    # Why use date_to in this case? We don't have thorough research to back this, but it felt a bit more intuitive.
    relevant_start_date = date_from if filter.display not in NON_TIME_SERIES_DISPLAY_TYPES else date_to

    query_params = {
        "date_from_active_users_adjusted": (relevant_start_date - diff).strftime("%Y-%m-%d %H:%M:%S"),
    }

    return format_params, query_params


def enumerate_time_range(filter: Filter, seconds_in_interval: int) -> list[str]:
    date_from = filter.date_from
    date_to = filter.date_to
    delta = timedelta(seconds=seconds_in_interval)
    time_range: list[str] = []

    if not date_from or not date_to:
        return time_range

    while date_from <= date_to:
        time_range.append(date_from.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")))
        date_from += delta
    return time_range


def determine_aggregator(entity: Entity, team: Team) -> str:
    """Return the relevant actor column."""
    if entity.math_group_type_index is not None:
        return f'"$group_{entity.math_group_type_index}"'
    elif team.aggregate_users_by_distinct_id:
        return "e.distinct_id"
    elif team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
        return "e.person_id"
    elif team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
        return f"if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id)"
    else:
        return "pdi.person_id"


def is_series_group_based(entity: Entity) -> bool:
    return entity.math == UNIQUE_GROUPS or (
        entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS and entity.math_group_type_index is not None
    )


F = TypeVar("F", Filter, PropertiesTimelineFilter)


def offset_time_series_date_by_interval(date: datetime.datetime, *, filter: F, team: Team) -> datetime.datetime:
    """If the insight is time-series, offset date according to the interval of the filter."""
    if filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
        return date
    if filter.interval == "month":
        date = (date + relativedelta(months=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "week":
        date = (date + timedelta(weeks=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter.interval == "hour":
        date = date + timedelta(hours=1)
    else:  # "day" is the default interval
        date = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    if date.tzinfo is None:
        date = date.replace(tzinfo=ZoneInfo(team.timezone))
    return date
