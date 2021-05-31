from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.util import format_ch_timestamp, get_earliest_timestamp
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, WEEKLY_ACTIVE
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter

MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}


def process_math(entity: Entity) -> Tuple[str, str, Dict[str, Optional[str]]]:
    aggregate_operation = "count(*)"
    params = {}
    join_condition = ""
    value = "toFloat64OrNull(JSONExtractRaw(properties, '{}'))".format(entity.math_property)
    if entity.math == "dau":
        join_condition = EVENT_JOIN_PERSON_SQL
        aggregate_operation = "count(DISTINCT person_id)"
    elif entity.math in MATH_FUNCTIONS:
        aggregate_operation = f"{MATH_FUNCTIONS[entity.math]}({value})"
        params = {"join_property_key": entity.math_property}

    return aggregate_operation, join_condition, params


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    dates = [
        item.strftime(
            "%Y-%m-%d{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    labels = [
        item.strftime(
            "%a. %-d %B{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    days = [
        item.strftime(
            "%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    return {
        "data": [float(c) for c in counts],
        "count": float(sum(counts)),
        "labels": labels,
        "days": days,
        **additional_values,
    }


def get_active_user_params(filter: Filter, entity: Entity, team_id: int) -> Dict[str, Any]:
    params = {}
    params.update({"prev_interval": "7 DAY" if entity.math == WEEKLY_ACTIVE else "30 day"})
    diff = timedelta(days=7) if entity.math == WEEKLY_ACTIVE else timedelta(days=30)
    if filter.date_from:
        params.update(
            {
                "parsed_date_from_prev_range": f"AND timestamp >= '{format_ch_timestamp(filter.date_from - diff, filter)}'"
            }
        )
    else:
        try:
            earliest_date = get_earliest_timestamp(team_id)
        except IndexError:
            raise ValueError("Active User queries require a lower date bound")
        else:
            params.update(
                {
                    "parsed_date_from_prev_range": f"AND timestamp >= '{format_ch_timestamp(earliest_date - diff, filter)}'"
                }
            )

    return params


def populate_entity_params(entity: Entity) -> Tuple[Dict, Dict]:
    params, content_sql_params = {}, {}
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        try:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)
            params = {**action_params}
            content_sql_params = {"entity_query": "AND {action_query}".format(action_query=action_query)}
        except:
            raise ValueError("Action does not exist")
    else:
        content_sql_params = {"entity_query": "AND event = %(event)s"}
        params = {"event": entity.id}

    return params, content_sql_params
