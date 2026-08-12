from typing import Any, Optional

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.utils import cast_timestamp_or_now


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
        "app_source": "event_usage",
        "count": 1,
        "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
    }
    get_producer(topic=KAFKA_APP_METRICS2).produce(topic=KAFKA_APP_METRICS2, data=payload)


def log_property_usage(
    property_name: str,
    property_type: str,
    team_id: int,
    user_id: Optional[int] = None,
) -> None:
    """
    Logs a property usage metric to Kafka.

    Args:
        property_name: The name of the property to log.
        property_type: The property filter type, e.g. "person" or "event".
        team_id: The ID of the team.
        user_id: The ID of the user. If not provided, defaults to "anonymous".
    """
    if not team_id:
        raise ValueError("Team ID must not be empty")
    if not property_name:
        raise ValueError("Property name must not be empty")
    if not property_type:
        raise ValueError("Property type must not be empty")

    payload = {
        "instance_id": f"property:{property_type}:{property_name}",
        "metric_name": "viewed",
        "team_id": team_id,
        "app_source_id": str(user_id) if user_id else "anonymous",
        "app_source": "property_usage",
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

    for event_name in query_metadata.get("events", []) or []:
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

    for property_reference in query_metadata.get("properties", []) or []:
        if not isinstance(property_reference, dict):
            continue
        property_name = property_reference.get("name")
        property_type = property_reference.get("type")
        if not property_name or not property_type:
            continue
        try:
            log_property_usage(
                property_name=property_name,
                property_type=property_type,
                team_id=team_id,
                user_id=user_id,
            )
        except Exception as e:
            # fail silently
            capture_exception(e)
