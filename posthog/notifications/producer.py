"""
Notification producer for emitting notification events to Kafka.

This is the primary API for product teams to send notifications.

IMPORTANT: This produces TEAM-SCOPED notification events, NOT user-specific.
User targeting is handled by the preference filter consumer based on user preferences.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

import structlog

logger = structlog.get_logger(__name__)

NotificationResourceType = Literal[
    "feature_flag",
    "insight",
    "dashboard",
    "alert",
    "approval",
    "workflow_error",
    "comment",
    "mention",
    "batch_export",
    "survey",
    "experiment",
    "cohort",
    "error_tracking",
]

NotificationPriority = Literal["low", "normal", "high", "urgent"]


@dataclass
class NotificationEvent:
    """
    Generic notification event data structure (TEAM-SCOPED, not user-specific).

    **Important**: This is a team/org-wide notification event. User targeting
    is handled by the preference filter consumer based on user preferences.

    Examples:
        # Feature flag created (team-wide)
        NotificationEvent(
            team_id=456,
            resource_type="feature_flag",
            event_type="created",
            resource_id="flag-uuid",
            title="Feature flag created",
            message="New feature flag 'new-signup-flow' was created",
            context={"actor_id": 123, "actor_name": "John Doe", "flag_key": "new-signup-flow"},
        )

        # Alert triggered (team-wide)
        NotificationEvent(
            team_id=456,
            resource_type="alert",
            event_type="triggered",
            resource_id="alert-uuid",
            title="Alert triggered",
            message="Pageview count exceeded threshold",
            priority="urgent",
            context={"threshold": 10000, "current": 12500, "triggered_by": "system"},
        )
    """

    team_id: int
    resource_type: NotificationResourceType
    event_type: str  # "created", "updated", "deleted", "triggered", etc.
    title: str
    message: str
    resource_id: Optional[str] = None
    context: Optional[dict] = None
    priority: NotificationPriority = "normal"


def produce_notification_event(event: NotificationEvent) -> None:
    """
    Produce a generic notification event to Kafka (TEAM-SCOPED).

    **Important**: This produces a team-wide notification event, NOT user-specific.
    The preference filter consumer will:
    1. Query all users in the team
    2. Check their notification preferences (cached)
    3. Fan-out to user-specific dispatch events
    4. Finally create DB records and send WebSocket messages

    This is the primary entry point for product teams to send notifications.

    Args:
        event: NotificationEvent instance (team-scoped)

    Raises:
        Exception: If Kafka production fails

    Example:
        from posthog.notifications.producer import produce_notification_event, NotificationEvent

        # Feature flag created - notify all team members (based on their preferences)
        produce_notification_event(
            NotificationEvent(
                team_id=team.id,
                resource_type="feature_flag",
                event_type="created",
                resource_id=str(feature_flag.id),
                title="Feature flag created",
                message=f"New feature flag '{feature_flag.key}' was created",
                context={
                    "actor_id": user.id,
                    "actor_name": user.first_name,
                    "flag_key": feature_flag.key,
                },
            )
        )
    """
    from posthog.kafka_client.client import KafkaProducer
    from posthog.kafka_client.topics import KAFKA_NOTIFICATION_EVENTS

    data = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "team_id": event.team_id,
        "resource_type": event.resource_type,
        "event_type": event.event_type,
        "resource_id": event.resource_id,
        "title": event.title,
        "message": event.message,
        "context": event.context or {},
        "priority": event.priority,
    }

    try:
        producer = KafkaProducer()
        future = producer.produce(
            topic=KAFKA_NOTIFICATION_EVENTS,
            data=data,
            key=f"team:{event.team_id}",  # Partition by team for ordering
        )
        future.get(timeout=5)  # Block briefly to ensure production
        logger.info(
            "notification_event_produced",
            team_id=event.team_id,
            resource_type=event.resource_type,
            event_type=event.event_type,
            title=event.title,
        )
    except Exception as e:
        logger.exception(
            "notification_event_production_failed",
            team_id=event.team_id,
            resource_type=event.resource_type,
            error=str(e),
        )
        raise


def broadcast_notification(
    team_id: int,
    resource_type: NotificationResourceType,
    event_type: str,
    title: str,
    message: str,
    resource_id: Optional[str] = None,
    context: Optional[dict] = None,
    priority: NotificationPriority = "normal",
    user_id: Optional[int] = None,
) -> bool:
    """
    Simplified notification API with exception handling.

    If user_id is provided, sends notification directly to that user.
    If user_id is None, sends to all team members based on their preferences.

    This function never raises exceptions - all errors are caught and logged.

    Args:
        team_id: Team ID
        resource_type: Type of resource (e.g., "feature_flag", "alert")
        event_type: Event type (e.g., "created", "triggered")
        title: Notification title
        message: Notification message
        resource_id: Optional resource ID
        context: Optional context dictionary
        priority: Notification priority (default: "normal")
        user_id: Optional user ID for direct user notification (bypasses preferences)

    Returns:
        bool: True if notification was sent successfully, False otherwise

    Example:
        from posthog.notifications.producer import broadcast_notification

        # Broadcast to all team members (based on preferences)
        broadcast_notification(
            team_id=team.id,
            resource_type="alert",
            event_type="triggered",
            title="Alert triggered",
            message="Pageview count exceeded 10k",
            resource_id=str(alert.id),
            priority="urgent",
            context={"threshold": 10000, "current": 12500},
        )

        # Send to specific user (bypasses preferences)
        broadcast_notification(
            team_id=team.id,
            user_id=user.id,
            resource_type="mention",
            event_type="created",
            title="You were mentioned",
            message=f"{actor.name} mentioned you in a comment",
        )
    """
    try:
        if user_id is not None:
            # Direct user notification - bypass preference filter
            from posthog.kafka_client.client import KafkaProducer
            from posthog.kafka_client.topics import KAFKA_NOTIFICATION_USER_DISPATCH

            data = {
                "user_id": user_id,
                "team_id": team_id,
                "resource_type": resource_type,
                "event_type": event_type,
                "resource_id": resource_id,
                "title": title,
                "message": message,
                "context": context or {},
                "priority": priority,
                "original_event_id": str(uuid.uuid4()),
            }

            producer = KafkaProducer()
            future = producer.produce(
                topic=KAFKA_NOTIFICATION_USER_DISPATCH,
                data=data,
                key=f"user:{user_id}",
            )
            future.get(timeout=5)

            logger.info(
                "notification_sent_to_user",
                team_id=team_id,
                user_id=user_id,
                resource_type=resource_type,
                event_type=event_type,
                title=title,
            )
        else:
            # Team-wide notification - goes through preference filter
            produce_notification_event(
                NotificationEvent(
                    team_id=team_id,
                    resource_type=resource_type,
                    event_type=event_type,
                    resource_id=resource_id,
                    title=title,
                    message=message,
                    context=context,
                    priority=priority,
                )
            )

        return True

    except Exception as e:
        logger.exception(
            "notification_broadcast_failed",
            team_id=team_id,
            user_id=user_id,
            resource_type=resource_type,
            event_type=event_type,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
