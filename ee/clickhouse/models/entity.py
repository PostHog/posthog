from typing import Any, Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.util import PersonPropertiesMode
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.entity import Entity


def get_entity_filtering_params(
    entity: Entity,
    team_id: int,
    table_name: str = "",
    *,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
) -> Tuple[Dict, Dict]:
    params: Dict[str, Any] = {}
    content_sql_params: Dict[str, str]
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = entity.get_action()
        action_query, action_params = format_action_filter(
            action, table_name=table_name, person_properties_mode=person_properties_mode,
        )
        params.update(action_params)
        content_sql_params = {"entity_query": f"AND {action_query}"}
    else:
        params["event"] = entity.id
        content_sql_params = {"entity_query": f"AND event = %(event)s"}

    return params, content_sql_params
