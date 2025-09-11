from collections.abc import Sequence
from typing import Any

from posthog.hogql.hogql import HogQLContext

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action.util import format_action_filter, format_action_filter_event_only
from posthog.models.entity import Entity
from posthog.queries.util import PersonPropertiesMode


def get_entity_filtering_params(
    allowed_entities: Sequence[Entity],
    team_id: int,
    hogql_context: HogQLContext,
    table_name: str = "",
    *,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
    person_id_joined_alias: str = "person_id",
    deep_filtering: bool = False,
) -> tuple[dict, dict]:
    """Return SQL condition for filtering events by allowed entities (events/actions).

    Events matching _at least one_ entity are included. If no entities are provided, _all_ events are included."""
    if not allowed_entities:
        return {}, {}

    params: dict[str, Any] = {}
    entity_clauses: list[str] = []
    action_ids_already_included: set[int] = set()  # Avoid duplicating action conditions
    events_already_included: set[str] = set()  # Avoid duplicating event conditions
    for entity in allowed_entities:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            if entity.id in action_ids_already_included or entity.id is None:
                continue
            action_ids_already_included.add(int(entity.id))
            action = entity.get_action()
            action_query, action_params = (
                format_action_filter(
                    team_id=team_id,
                    action=action,
                    table_name=table_name,
                    person_properties_mode=person_properties_mode,
                    person_id_joined_alias=person_id_joined_alias,
                    hogql_context=hogql_context,
                )
                if not deep_filtering
                else format_action_filter_event_only(action)
            )
            params.update(action_params)
            entity_clauses.append(action_query)
        else:
            if entity.id is None:  # all events
                continue
            if entity.id in events_already_included:
                continue
            events_already_included.add(str(entity.id))
            params[f"event_{entity.order}"] = entity.id
            entity_clauses.append(f"event = %(event_{entity.order})s")

    if len(entity_clauses) == 0:
        return {}, {"entity_query": "AND 1 = 1"}

    combined_entity_clauses = f"({' OR '.join(entity_clauses)})" if len(entity_clauses) > 1 else entity_clauses[0]
    return params, {"entity_query": f"AND {combined_entity_clauses}"}
