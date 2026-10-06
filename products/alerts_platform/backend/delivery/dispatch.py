"""One delivery, end to end.

Ties together what a notification says, where the last one landed, and the provider that sends
it. Which destinations an alert has is resolved before this, so a change to that resolution
reaches no transport.
"""

from products.alerts_platform.backend.delivery.message import AlertMessage, build_message
from products.alerts_platform.backend.delivery.telemetry import record_delivery
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy, ThreadKey, ThreadStore
from products.alerts_platform.backend.delivery.transport import DeliveryTransport, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AnnouncedTransition,
    EvaluationAnnouncement,
)


def deliver(
    *,
    transport: DeliveryTransport,
    thread_store: ThreadStore,
    team_id: int,
    configuration_id: str,
    evaluation_key: str,
    target: AlertDestinationData,
    announcement: EvaluationAnnouncement,
) -> None:
    channel_target = transport.channel_target(target)
    busy = 0

    for transition in announcement.transitions:
        key = _thread_key(
            configuration_id=configuration_id,
            provider=transport.provider,
            channel_target=channel_target,
            transition=transition,
        )
        if key is None:
            _send(
                transport=transport,
                team_id=team_id,
                configuration_id=configuration_id,
                target=target,
                message=build_message(announcement, transition),
                in_reply_to=None,
            )
            continue

        try:
            claim = thread_store.claim(key, evaluation_key)
        except ThreadBusy:
            # Another attempt may still be posting, so sending now could put the same message
            # in the channel twice. The holder may also have died, and then its claim frees
            # this thread only when it goes stale. The caller waits and runs the send again.
            busy += 1
            continue
        if claim is None:
            continue

        try:
            sent = _send(
                transport=transport,
                team_id=team_id,
                configuration_id=configuration_id,
                target=target,
                message=build_message(announcement, transition),
                in_reply_to=claim.handle,
            )
        except Exception:
            thread_store.release(claim)
            raise
        thread_store.delivered(claim, sent)

    if busy:
        raise ThreadBusy(f"{busy} of {len(announcement.transitions)} threads are held by another send")


def _send(
    *,
    transport: DeliveryTransport,
    team_id: int,
    configuration_id: str,
    target: AlertDestinationData,
    message: AlertMessage,
    in_reply_to: MessageHandle | None,
) -> MessageHandle | None:
    try:
        sent = transport.deliver(team_id=team_id, target=target, message=message, in_reply_to=in_reply_to)
    except Exception:
        # Every failure class. Counting only the refusals a provider names leaves an outage
        # reading as no delivery attempted at all.
        record_delivery(
            team_id=team_id, configuration_id=configuration_id, provider=transport.provider, succeeded=False
        )
        raise
    record_delivery(team_id=team_id, configuration_id=configuration_id, provider=transport.provider, succeeded=True)
    return sent


def _thread_key(
    *,
    configuration_id: str,
    provider: str,
    channel_target: str,
    transition: AnnouncedTransition,
) -> ThreadKey | None:
    """Which conversation this message belongs to, or None when it belongs to none.

    A message about no firing, which is a failed or a turned-off check, continues no
    conversation and starts none. Keying one on the absent firing would thread every such
    message for a configuration into the first one, which is the defect the episode prevents.
    """
    if transition.episode_started_at is None:
        return None
    return ThreadKey(
        configuration_id=configuration_id,
        grouping_key=transition.grouping_key,
        provider=provider,
        channel_target=channel_target,
        episode_started_at=transition.episode_started_at,
    )
