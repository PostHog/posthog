"""One delivery, end to end.

Ties together what a notification says, where the last one landed, and the provider that sends
it. Which destinations an alert has is resolved before this, so a change to that resolution
reaches no transport.
"""

from datetime import UTC

from django.utils import timezone

import structlog

from products.alerts_platform.backend.delivery.message import AlertMessage, build_message
from products.alerts_platform.backend.delivery.refusal_notices import notify_refused
from products.alerts_platform.backend.delivery.root_state import state_line
from products.alerts_platform.backend.delivery.telemetry import record_delivery
from products.alerts_platform.backend.delivery.thread_store import Opening, ThreadBusy, ThreadKey, ThreadStore
from products.alerts_platform.backend.delivery.transport import (
    DeliveryError,
    DeliveryTransport,
    DestinationMisconfigured,
    DestinationRefused,
    MessageHandle,
    RootEditor,
    RootImageEditor,
)
from products.alerts_platform.backend.facade.contracts import (
    NO_LATE_IMAGE,
    AlertDestinationData,
    AnnouncedTransition,
    DeliveryPath,
    EvaluationAnnouncement,
    IncidentAction,
    LateImageResult,
    MessageImage,
    MessageLink,
)
from products.alerts_platform.backend.logic.platform_reads import alert_snapshot
from products.alerts_platform.backend.temporal.metrics import (
    DeliveryOutcomeLabel,
    increment_deliveries,
    increment_root_edit_failures,
    record_delivery_lag,
    safe_record,
)

logger = structlog.get_logger(__name__)


def deliver(
    *,
    transport: DeliveryTransport,
    thread_store: ThreadStore,
    team_id: int,
    configuration_id: str,
    evaluation_key: str,
    target: AlertDestinationData,
    destination_id: str | None,
    announcement: EvaluationAnnouncement,
    incident_action: IncidentAction | None = None,
    source_alert_url: str | None = None,
    source_incident_key: str | None = None,
    project: MessageLink | None = None,
) -> None:
    channel_target = transport.channel_target(target)
    source = announcement.source.value
    busy = 0

    for transition in announcement.transitions:
        # On the first transition, because a retry skips a message already delivered and waits out
        # a held one, so the overflow notice is sent once, and with the message that opens the batch.
        overflowed = announcement.overflowed if transition is announcement.transitions[0] else 0
        key = _thread_key(
            configuration_id=configuration_id,
            provider=transport.provider,
            channel_target=channel_target,
            transition=transition,
        )
        try:
            claim = thread_store.claim(key, evaluation_key)
        except ThreadBusy:
            # Another attempt may still be posting, so sending now could put the same message
            # in the channel twice. The holder may also have died, and then its claim frees
            # this thread only when it goes stale. The caller waits and runs the send again.
            busy += 1
            safe_record(increment_deliveries, source, transport.provider, DeliveryPath.NATIVE.value, "busy")
            continue
        if claim is None:
            safe_record(
                increment_deliveries, source, transport.provider, DeliveryPath.NATIVE.value, "already_delivered"
            )
            continue

        try:
            sent = _send(
                transport=transport,
                team_id=team_id,
                configuration_id=configuration_id,
                target=target,
                destination_id=destination_id,
                message=build_message(
                    announcement,
                    transition,
                    team_id=team_id,
                    incident_action=incident_action,
                    source_alert_url=source_alert_url,
                    overflowed=overflowed,
                    source_incident_key=source_incident_key,
                    project=project,
                ),
                in_reply_to=claim.handle,
            )
        except Exception:
            thread_store.release(claim)
            raise
        if claim.handle is not None:
            # A reply landed under an opening message, so the opening message catches up. It runs
            # before `delivered` releases the claim, so edits to one root happen in send order and
            # a slow edit cannot land after a newer one.
            _edit_root(transport=transport, team_id=team_id, target=target, root=claim.handle, key=key)
        thread_store.delivered(claim, sent)

    if busy:
        raise ThreadBusy(f"{busy} of {len(announcement.transitions)} threads are held by another send")


def _send(
    *,
    transport: DeliveryTransport,
    team_id: int,
    configuration_id: str,
    target: AlertDestinationData,
    destination_id: str | None,
    message: AlertMessage,
    in_reply_to: MessageHandle | None,
) -> MessageHandle | None:
    try:
        sent = transport.deliver(team_id=team_id, target=target, message=message, in_reply_to=in_reply_to)
    except Exception as error:
        # Every failure class. Counting only the refusals a provider names leaves an outage
        # reading as no delivery attempted at all. A transport words its own refusals safely, and
        # any other exception's text can carry a credential URL, so it is named by class.
        record_delivery(
            team_id=team_id,
            configuration_id=configuration_id,
            provider=transport.provider,
            destination_id=destination_id,
            succeeded=False,
            error=str(error) if isinstance(error, DeliveryError) else type(error).__name__,
        )
        outcome: DeliveryOutcomeLabel = "misconfigured" if isinstance(error, DestinationMisconfigured) else "failed"
        safe_record(increment_deliveries, message.source.value, transport.provider, DeliveryPath.NATIVE.value, outcome)
        if isinstance(error, DestinationRefused):
            notify_refused(
                team_id=team_id,
                message=message,
                # Where the send went, not the destination id: a converted alert has one id per event
                # kind, so one broken URL would be noticed once for each kind it was refused on.
                destination=transport.channel_target(target),
                refusal=error,
            )
        raise
    record_delivery(
        team_id=team_id,
        configuration_id=configuration_id,
        provider=transport.provider,
        destination_id=destination_id,
        succeeded=True,
    )
    safe_record(increment_deliveries, message.source.value, transport.provider, DeliveryPath.NATIVE.value, "sent")
    safe_record(record_delivery_lag, message.source.value, transport.provider, _lag_ms(message.transition))
    return sent


def _lag_ms(transition: AnnouncedTransition) -> int:
    # History rows come back from ClickHouse without a zone, and their times are UTC.
    decided_at = transition.occurred_at
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=UTC)
    return max(0, int((timezone.now() - decided_at).total_seconds() * 1000))


def _edit_root(
    *,
    transport: DeliveryTransport,
    team_id: int,
    target: AlertDestinationData,
    root: MessageHandle,
    key: ThreadKey,
) -> None:
    """Puts the group's current state on the message that opened its conversation.

    Best effort: the reply already landed, so a failed edit is logged and never fails the send.
    """
    if not isinstance(transport, RootEditor) or not root.root_content:
        return
    try:
        line = _current_state_line(team_id, key)
        if line is not None:
            transport.edit_root(team_id=team_id, target=target, root=root, state_line=line)
    except Exception:
        logger.exception("alerts_platform.root_edit_failed", provider=transport.provider)
        safe_record(increment_root_edit_failures, transport.provider)


def _current_state_line(team_id: int, key: ThreadKey) -> str | None:
    snapshot = alert_snapshot(team_id, key.configuration_id, key.grouping_key)
    return state_line(snapshot, episode_started_at=key.episode_started_at, as_of=timezone.now())


# Only the claim carries this key, so it never enters the conversation's delivered evaluations.
LATE_IMAGE_KEY_PREFIX = "late-image:"


def add_late_image(
    *,
    transport: DeliveryTransport,
    thread_store: ThreadStore,
    team_id: int,
    configuration_id: str,
    evaluation_key: str,
    target: AlertDestinationData,
    transitions: tuple[AnnouncedTransition, ...],
    image: MessageImage,
) -> LateImageResult:
    """Puts an image that was not ready when these transitions went out into the messages they opened.

    Only an opening message changes, because the thread store keeps the handle of no other. A
    conversation is claimed for the edit, so it never interleaves with a send or a state edit to
    the same message, and the image stays in the content later state edits start from.
    """
    if not isinstance(transport, RootImageEditor):
        return NO_LATE_IMAGE
    channel_target = transport.channel_target(target)
    result = NO_LATE_IMAGE
    for transition in transitions:
        key = _thread_key(
            configuration_id=configuration_id,
            provider=transport.provider,
            channel_target=channel_target,
            transition=transition,
        )
        opening = thread_store.opening(key, evaluation_key)
        if opening == Opening.REPLY:
            continue
        try:
            claim = (
                thread_store.claim(key, f"{LATE_IMAGE_KEY_PREFIX}{evaluation_key}") if opening == Opening.ROOT else None
            )
        except ThreadBusy:
            claim = None
        if claim is None:
            result += LateImageResult(edited=0, waiting=1)
            continue
        if claim.handle is None:
            thread_store.release(claim)
            continue
        try:
            content = transport.add_root_image(
                team_id=team_id,
                target=target,
                root=claim.handle,
                image=image,
                state_line=_current_state_line(team_id, key),
            )
        except Exception:
            thread_store.release(claim)
            raise
        thread_store.release(claim, root_content=content)
        # None means the message has no image slot, which no retry changes.
        if content is not None:
            result += LateImageResult(edited=1, waiting=0)
    return result


def _thread_key(
    *,
    configuration_id: str,
    provider: str,
    channel_target: str,
    transition: AnnouncedTransition,
) -> ThreadKey:
    """Which conversation this message belongs to.

    A message about no known firing, which is a failed or a turned-off check or the resolve of a
    firing that began before the platform recorded starts, continues no conversation. Keying one
    on the absent firing would thread every such message for a configuration into the first one,
    which is the defect the episode prevents. So it is keyed on its own transition: it starts a
    conversation nothing else joins, and a retried delivery still finds its claim and sends nothing.
    """
    return ThreadKey(
        configuration_id=configuration_id,
        grouping_key=transition.grouping_key,
        provider=provider,
        channel_target=channel_target,
        episode_started_at=transition.episode_started_at or transition.occurred_at,
    )
