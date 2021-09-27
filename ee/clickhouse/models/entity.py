from typing import Any, Dict, Optional, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.entity import Entity


def get_entity_filtering_params(
    entity: Entity,
    team_id: int,
    table_name: str = "",
    *,
    person_properties_column: str,
    with_prop_filters: bool = False,
) -> Tuple[Dict, Dict]:
    params: Dict[str, Any] = {}
    content_sql_params: Dict[str, str]
    prop_filters = ""
    if with_prop_filters:
        prop_filters, params = parse_prop_clauses(
            entity.properties,
            team_id,
            table_name=table_name,
            person_properties_column=person_properties_column,
            prepend=f"entity",
        )
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = entity.get_action()
        action_query, action_params = format_action_filter(
            action, table_name=table_name, person_properties_column=person_properties_column
        )
        params.update(action_params)
        content_sql_params = {"entity_query": f"AND {action_query} {prop_filters}"}
    else:
        params["event"] = entity.id
        content_sql_params = {"entity_query": f"AND event = %(event)s {prop_filters}"}

    return params, content_sql_params
