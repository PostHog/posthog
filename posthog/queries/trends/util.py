import datetime
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from rest_framework.exceptions import ValidationError

from posthog.constants import UNIQUE_USERS, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.event.sql import EVENT_JOIN_PERSON_SQL
from posthog.models.filters import Filter, PathFilter
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.util import get_earliest_timestamp

PROPERTY_MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}

COUNT_PER_ACTOR_MATH_FUNCTIONS = {
    "avg_count_per_actor": "avg",
    "min_count_per_actor": "min",
    "max_count_per_actor": "max",
    "median_count_per_actor": "quantile(0.50)",
    "p90_count_per_actor": "quantile(0.90)",
    "p95_count_per_actor": "quantile(0.95)",
    "p99_count_per_actor": "quantile(0.99)",
}


def process_math(
    entity: Entity, team: Team, event_table_alias: Optional[str] = None, person_id_alias: str = "person_id"
) -> Tuple[str, str, Dict[str, Any]]:
    aggregate_operation = "count(*)"
    join_condition = ""
    params: Dict[str, Any] = {}

    if entity.math == UNIQUE_USERS:
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
                {"math_property": "This field is required when `math` is set to a function."}, code="required"
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

    return aggregate_operation, join_condition, params


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    labels = [item.strftime("%-d-%b-%Y{}".format(" %H:%M" if filter.interval == "hour" else "")) for item in stats[0]]
    days = [item.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")) for item in stats[0]]
    return {
        "data": [float(c) for c in counts],
        "count": float(sum(counts)),
        "labels": labels,
        "days": days,
        **additional_values,
    }


def get_active_user_params(
    filter: Union[Filter, PathFilter], entity: Entity, team_id: int
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    diff = timedelta(days=7 if entity.math == WEEKLY_ACTIVE else 30)

    date_from: datetime.datetime
    if filter.date_from:
        date_from = filter.date_from
    else:
        try:
            date_from = get_earliest_timestamp(team_id)
        except IndexError:
            raise ValidationError("Active User queries require a lower date bound")

    format_params = {
        # Not 7 and 30 because the day of the date marker is included already in the query (`+ INTERVAL 1 DAY`)
        "prev_interval": "6 DAY" if entity.math == WEEKLY_ACTIVE else "29 DAY",
        "parsed_date_from_prev_range": f"AND toDateTime(timestamp, 'UTC') >= toDateTime(%(date_from_active_users_adjusted)s, %(timezone)s)",
    }
    query_params = {"date_from_active_users_adjusted": (date_from - diff).strftime("%Y-%m-%d %H:%M:%S")}

    return format_params, query_params


def enumerate_time_range(filter: Filter, seconds_in_interval: int) -> List[str]:
    date_from = filter.date_from
    date_to = filter.date_to
    delta = timedelta(seconds=seconds_in_interval)
    time_range: List[str] = []

    if not date_from or not date_to:
        return time_range

    while date_from <= date_to:
        time_range.append(date_from.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" else "")))
        date_from += delta
    return time_range
