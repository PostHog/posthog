"""In-app delivery, to the PostHog notification inbox of the people subscribed to an alert.

The user ids arrive resolved, like an email destination's addresses. The product that owns the
subscriptions applies its access rules before the platform sees an id. Each notification carries
an idempotency key per transition and recipient, so a retried delivery notifies nobody twice.

A notification starts no conversation, so a send returns no handle and a resolve is a new one.
"""

from typing import Final, cast
from urllib.parse import urlsplit

from products.alerts_platform.backend.delivery.message import AlertMessage, transition_delivery_key
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.wire import credential_digest
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationResourceType,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

PROVIDER: Final = "in_app"
MAX_TITLE_CHARS: Final = 100

# A person turns off each type in their notification settings. A resolve has no type of its own, so
# it shares the firing type, and turning off alert notifications turns off both.
_NOTIFICATION_TYPES: Final[dict[AlertEventKind, NotificationType]] = {
    AlertEventKind.FIRING: NotificationType.ALERT_FIRING,
    AlertEventKind.RESOLVED: NotificationType.ALERT_FIRING,
    AlertEventKind.ERRORED: NotificationType.PIPELINE_FAILURE,
    AlertEventKind.BROKEN: NotificationType.PIPELINE_FAILURE,
}


def body_for(message: AlertMessage) -> str:
    return "; ".join([*(f"{detail.label}: {detail.value}" for detail in message.details), *message.context])


class InAppTransport:
    provider = PROVIDER

    def channel_target(self, target: AlertDestinationData) -> str:
        return credential_digest("\n".join(str(user_id) for user_id in sorted(target.get("in_app_user_ids", []))))

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        user_ids = target.get("in_app_user_ids") or []
        if not user_ids:
            raise DeliveryError("This in-app destination has no recipients.")
        notification_type = _NOTIFICATION_TYPES.get(message.transition.kind)
        if notification_type is None:
            raise DeliveryError(f"In-app notifications have no type for {message.transition.kind.value} alerts.")
        key = transition_delivery_key(message)
        resource_type = target.get("in_app_resource_type")
        for user_id in user_ids:
            create_notification(
                NotificationData(
                    team_id=team_id,
                    notification_type=notification_type,
                    priority=Priority.NORMAL,
                    title=message.headline[:MAX_TITLE_CHARS],
                    body=body_for(message),
                    target_type=TargetType.USER,
                    target_id=str(user_id),
                    resource_type=cast(NotificationResourceType, resource_type) if resource_type else None,
                    resource_id=target.get("in_app_resource_id", ""),
                    source_url=target.get("in_app_url") or urlsplit(message.alert_url).path,
                    idempotency_key=f"{key}:{user_id}",
                )
            )
        return None
