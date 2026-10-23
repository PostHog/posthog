from typing import Any, Optional

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.utils import cast_timestamp_or_now

EVENT_USAGE_APP_SOURCE = "event_usage"
PROPERTY_USAGE_APP_SOURCE = "property_usage"

# A single query can reference very many events or properties (wide HogQL selects, long `event IN (...)`
# lists). Cap what one execution logs so a pathological query can't flood app_metrics2.
MAX_EVENTS_LOGGED_PER_QUERY = 50
MAX_PROPERTIES_LOGGED_PER_QUERY = 50


def property_usage_instance_id(property_type: str, property_name: str, group_type_index: int | None = None) -> str:
    """The app_metrics2 identity of one property definition. Rows keep it forever, so the shape must not change.

    Group properties carry their group type index, because each group type has its own definitions and the same
    name can exist on several of them. The index segment is an integer and the type is a fixed word, so no two
    definitions map to the same id.
    """
    if property_type == "group":
        if not isinstance(group_type_index, int) or isinstance(group_type_index, bool):
            raise ValueError("Group properties need a group type index")
        return f"property:group:{group_type_index}:{property_name}"
    return f"property:{property_type}:{property_name}"


def log_event_usage(
    event_name: str,
    team_id: int,
    user_id: Optional[int] = None,
) -> None:
    """
    Logs an event usage metric to Kafka.

    Args:
        event_name: The name of the event to log.
        team_id: The ID of the team.
        user_id: The ID of the user. If not provided, defaults to "anonymous".
    """
    if not team_id:
        raise ValueError("Team ID must not be empty")
    if not event_name:
        raise ValueError("Event name must not be empty")

    payload = {
        "instance_id": f"event:{event_name}",
        "metric_name": "viewed",
        "team_id": team_id,
        "app_source_id": str(user_id) if user_id else "anonymous",
        "app_source": EVENT_USAGE_APP_SOURCE,
        "count": 1,
        "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
    }
    get_producer(topic=KAFKA_APP_METRICS2).produce(topic=KAFKA_APP_METRICS2, data=payload)


def log_property_usage(
    property_type: str,
    property_name: str,
    team_id: int,
    user_id: Optional[int] = None,
    group_type_index: Optional[int] = None,
) -> None:
    """
    Logs a property usage metric to Kafka.

    Args:
        property_type: PropertyDefinition-style type (event | person | group | session).
        property_name: The name of the property to log.
        team_id: The ID of the team.
        group_type_index: The group type index. Required for group properties.
        user_id: The ID of the user. If not provided, defaults to "anonymous".
    """
    if not team_id:
        raise ValueError("Team ID must not be empty")
    if not property_type or not property_name:
        raise ValueError("Property type and name must not be empty")

    payload = {
        "instance_id": property_usage_instance_id(property_type, property_name, group_type_index),
        "metric_name": "viewed",
        "team_id": team_id,
        "app_source_id": str(user_id) if user_id else "anonymous",
        "app_source": PROPERTY_USAGE_APP_SOURCE,
        "count": 1,
        "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
    }
    get_producer(topic=KAFKA_APP_METRICS2).produce(topic=KAFKA_APP_METRICS2, data=payload)


def log_event_usage_from_query_metadata(
    query_metadata: dict[str, Any],
    team_id: int,
    user_id: Optional[int] = None,
):
    """
    Logs event and property usage from query metadata.

    Args:
        query_metadata: The query metadata containing events and properties.
        team_id: The ID of the team.
        user_id: The ID of the user. If not provided, defaults to "anonymous".
    """
    if not query_metadata or not isinstance(query_metadata, dict):
        return

    events = query_metadata.get("events") or []
    if not isinstance(events, list):
        events = []
    for event_name in events[:MAX_EVENTS_LOGGED_PER_QUERY]:
        if not event_name:
            continue
        try:
            log_event_usage(
                event_name=event_name,
                team_id=team_id,
                user_id=user_id,
            )
        except Exception as e:
            # fail silently
            capture_exception(e)

    properties = query_metadata.get("properties") or []
    if not isinstance(properties, list):
        return
    for entry in properties[:MAX_PROPERTIES_LOGGED_PER_QUERY]:
        if not isinstance(entry, dict):
            continue
        property_type = entry.get("type")
        property_name = entry.get("name")
        if not property_type or not property_name:
            continue
        try:
            log_property_usage(
                property_type=property_type,
                property_name=property_name,
                team_id=team_id,
                user_id=user_id,
                group_type_index=entry.get("group_type_index"),
            )
        except Exception as e:
            # fail silently
            capture_exception(e)
