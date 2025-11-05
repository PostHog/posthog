from typing import Any, Optional

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import KafkaProducer
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
    KafkaProducer().produce(topic=KAFKA_APP_METRICS2, data=payload)


def log_event_usage_from_query_metadata(
    query_metadata: dict[str, Any],
    team_id: int,
    user_id: Optional[int] = None,
):
    """
    Logs event usage from query metadata.

    Args:
        query_metadata: The query metadata containing events.
        team_id: The ID of the team.
        user_id: The ID of the user. If not provided, defaults to "anonymous".
    """
    if not query_metadata or not isinstance(query_metadata, dict) or not query_metadata.get("events", []):
        return

    for event_name in query_metadata["events"]:
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
