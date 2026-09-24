"""One delivery, end to end.

Ties together what a notification says, where the last one landed, and the provider that sends
it. Which destinations an alert has is resolved before this, so a change to that resolution
reaches no transport.
"""

from products.alerts.backend.delivery.message import build_message
from products.alerts.backend.delivery.telemetry import record_delivery
from products.alerts.backend.delivery.thread_store import ThreadStore
from products.alerts.backend.delivery.transport import DeliveryError, DeliveryTransport
from products.alerts.backend.facade.contracts import AlertDestinationData, EvaluationAnnouncement


def deliver(
    *,
    transport: DeliveryTransport,
    thread_store: ThreadStore,
    team_id: int,
    configuration_id: str,
    target: AlertDestinationData,
    announcement: EvaluationAnnouncement,
) -> None:
    channel_target = transport.channel_target(target)

    for notification in announcement.notifications:
        handle = thread_store.handle_for(
            configuration_id=configuration_id,
            notification_key=notification.notification_key,
            provider=transport.provider,
            channel_target=channel_target,
        )
        for transition in notification.transitions:
            message = build_message(announcement, transition)
            try:
                sent = transport.deliver(team_id=team_id, target=target, message=message, in_reply_to=handle)
            except DeliveryError:
                record_delivery(
                    team_id=team_id,
                    configuration_id=configuration_id,
                    provider=transport.provider,
                    succeeded=False,
                )
                raise
            record_delivery(
                team_id=team_id, configuration_id=configuration_id, provider=transport.provider, succeeded=True
            )
            # Only the first message of a conversation is remembered. A later one replies into
            # it, and remembering the reply would move the thread onto itself.
            if sent is not None and handle is None:
                thread_store.remember(
                    configuration_id=configuration_id,
                    notification_key=notification.notification_key,
                    provider=transport.provider,
                    channel_target=channel_target,
                    handle=sent,
                )
                handle = sent
