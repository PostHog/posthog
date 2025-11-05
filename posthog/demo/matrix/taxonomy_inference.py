import json
import datetime
from typing import Optional

from posthog.models import EventDefinition, EventProperty, PropertyDefinition
from posthog.models.group.sql import GROUPS_TABLE
from posthog.models.person.sql import PERSONS_TABLE
from posthog.models.property_definition import PropertyType


def infer_taxonomy_for_team(team_id: int) -> tuple[int, int, int]:
    """Infer event and property definitions based on ClickHouse data.

    In production, the plugin server is responsible for this - but in demo data we insert directly to ClickHouse.
    """
    # Event definitions, with `last_seen_at`
    events_last_seen_at = _get_events_last_seen_at(team_id)
    event_definitions = EventDefinition.objects.bulk_create(
        [
            EventDefinition(team_id=team_id, name=event, last_seen_at=last_seen_at)
            for event, last_seen_at in events_last_seen_at.items()
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )

    # Property definitions, with types
    property_types = _get_property_types(team_id)
    property_definitions = PropertyDefinition.objects.bulk_create(
        [
            PropertyDefinition(
                team_id=team_id,
                name=name,
                property_type=property_type,
                is_numerical=property_type == PropertyType.Numeric,
                type=type,
                group_type_index=group_type_index,
            )
            for (type, name, group_type_index), property_type in property_types.items()
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )

    # (event, property) pairs
    event_property_pairs = _get_event_property_pairs(team_id)
    event_properties = EventProperty.objects.bulk_create(
        [
            EventProperty(team_id=team_id, event=event, property=property_key)
            for event, property_key in event_property_pairs
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )

    return len(event_definitions), len(property_definitions), len(event_properties)


def _get_events_last_seen_at(team_id: int) -> dict[str, datetime.datetime]:
    from posthog.clickhouse.client import sync_execute

    return dict(sync_execute(_GET_EVENTS_LAST_SEEN_AT, {"team_id": team_id}))


InferredPropertyKey = tuple[PropertyDefinition.Type, str, Optional[int]]
InferredProperties = dict[InferredPropertyKey, Optional[PropertyType]]


def _get_property_types(team_id: int) -> InferredProperties:
    """Determine property types based on ClickHouse data."""
    from posthog.clickhouse.client import sync_execute

    property_types: InferredProperties = {
        (PropertyDefinition.Type.EVENT, property_key, None): _infer_property_type(sample_json_value)
        for property_key, sample_json_value in sync_execute(
            _GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id}
        )
    }

    for property_key, sample_json_value, _ in sync_execute(
        _GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id}
    ):
        if property_key not in property_types:
            property_types[(PropertyDefinition.Type.PERSON, property_key, None)] = _infer_property_type(
                sample_json_value
            )
    for property_key, sample_json_value, group_type_index in sync_execute(
        _GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id}
    ):
        if property_key not in property_types:
            property_types[(PropertyDefinition.Type.GROUP, property_key, group_type_index)] = _infer_property_type(
                sample_json_value
            )

    return property_types


def _infer_property_type(sample_json_value: str) -> Optional[PropertyType]:
    """Parse the provided sample value as JSON and return its property type."""
    parsed_value = json.loads(sample_json_value)
    if isinstance(parsed_value, bool):
        return PropertyType.Boolean
    if isinstance(parsed_value, float | int):
        return PropertyType.Numeric
    if isinstance(parsed_value, str):
        return PropertyType.String
    return None


def _get_event_property_pairs(team_id: int) -> list[tuple[str, str]]:
    """Determine which properties have been since with which events based on ClickHouse data."""
    from posthog.clickhouse.client import sync_execute

    return [row[0] for row in sync_execute(_GET_EVENT_PROPERTIES, {"team_id": team_id})]


_GET_EVENTS_LAST_SEEN_AT = """
SELECT event, max(timestamp) AS last_seen_at
FROM events
WHERE team_id = %(team_id)s
GROUP BY event
"""

_GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES = """
WITH property_tuples AS (
    SELECT DISTINCT ON (property_tuple.1) arrayJoin(JSONExtractKeysAndValuesRaw(properties)) AS property_tuple
    FROM events
    WHERE team_id = %(team_id)s
)
SELECT property_tuple.1 AS property_key, property_tuple.2 AS sample_json_value FROM property_tuples
"""
_GET_ACTOR_PROPERTY_SAMPLE_JSON_VALUES = """
WITH property_tuples AS (
    SELECT arrayJoin(JSONExtractKeysAndValuesRaw({properties_column})) AS property_key_value_pair, {group_type_index_column} as index FROM {table_name}
    WHERE team_id = %(team_id)s
)
SELECT
    property_key_value_pair.1 AS property_key,
    anyLast(property_key_value_pair.2) AS sample_json_value,
    index AS group_type_index
FROM property_tuples
GROUP BY property_key, group_type_index
"""
_GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES = _GET_ACTOR_PROPERTY_SAMPLE_JSON_VALUES.format(
    table_name=PERSONS_TABLE, properties_column="properties", group_type_index_column="null"
)
_GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES = _GET_ACTOR_PROPERTY_SAMPLE_JSON_VALUES.format(
    table_name=GROUPS_TABLE, properties_column="group_properties", group_type_index_column="group_type_index"
)

_GET_EVENT_PROPERTIES = """
SELECT DISTINCT (event, arrayJoin(JSONExtractKeys(properties))) FROM events
WHERE team_id = %(team_id)s
"""
