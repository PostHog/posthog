from typing import Any, Dict, List, Tuple

from ee.clickhouse.models.action import format_action_filter
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Entity, Filter, Team


def event_entity_to_query(entity: Entity, team: Team, prepend="event_entity") -> Tuple[str, Dict]:
    event_query = "event = %({})s ".format(prepend)
    params = {prepend: entity.id}

    if entity.properties:
        from ee.clickhouse.models.property import parse_prop_clauses

        prop_query, prop_params = parse_prop_clauses(
            entity.properties,
            team_id=team.pk,
            prepend="{}_props".format(prepend),
            allow_denormalized_props=False,
            has_person_id_joined=False,
        )
        event_query += prop_query
        params = {**params, **prop_params}

    return f"({event_query})", params


def entity_query_conditions(filter: Filter, team: Team) -> Tuple[List[str], Dict]:
    entity_conditions = []
    params: Dict[str, Any] = {}
    for index, entity in enumerate(filter.entities):
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = entity.get_action()
            action_query, action_params = format_action_filter(action, prepend=f"action_{index}")
            entity_conditions.append(action_query)
            params = {**params, **action_params}
        else:
            event_query, event_params = event_entity_to_query(entity, team, prepend=f"event_{index}")
            entity_conditions.append(event_query)
            params = {**params, **event_params}

    return entity_conditions, params
