"""Sends the incident actions an edit owes the incident managers it moved firings between.

Deliveries always follow the current routes and destinations. When an edit moves a firing group onto
an incident manager, it hears the trigger now, so the resolve it gets later closes something. When an
edit moves one off an incident manager, it hears the resolve, or its incident would stay open.

What each send says comes from the history row that opened the firing, which is the row its trigger
was sent from. Nothing new is written to history: a handoff is not a check, and a history or
comparison read must not see a second firing.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import cast

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery.dispatch import SendTally, deliver
from products.alerts_platform.backend.delivery.evaluation import _TRANSPORTS
from products.alerts_platform.backend.delivery.pagerduty import source_incident_key
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    HandoffSend,
    IncidentAction,
    MessageLink,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic import delivery_holds, destination_handoff
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.platform_alert_events import opening_transitions
from products.alerts_platform.backend.logic.platform_reads import rule_metadata
from products.alerts_platform.backend.models import AlertDestination, AlertReceiver, PlatformAlert

logger = structlog.get_logger(__name__)


@frozen
class HandoffTarget:
    send: HandoffSend
    data: AlertDestinationData


def deliver_handoff(request: AlertDeliveryRequest) -> int:
    """Sends a handoff the delivery workflow carries, to destinations read now by id. A gained
    destination that was disabled or removed since is skipped."""
    own_ids = [send.destination_id for send in request.handoff if not send.routed]
    routed_ids = [send.destination_id for send in request.handoff if send.routed]
    own = {
        str(row_id): (config, enabled)
        for row_id, config, enabled in AlertDestination.objects.for_team(request.team_id)
        .filter(configuration_id=request.configuration_id, id__in=own_ids)
        .values_list("id", "config", "enabled")
    }
    routed = {
        str(row_id): (config, enabled)
        for row_id, config, enabled in AlertReceiver.objects.for_team(request.team_id)
        .filter(id__in=routed_ids)
        .values_list("id", "config", "enabled")
    }
    targets: list[HandoffTarget] = []
    for send in request.handoff:
        found = (routed if send.routed else own).get(send.destination_id)
        if found is None or (send.gained and not found[1]):
            continue
        targets.append(HandoffTarget(send=send, data=cast(AlertDestinationData, found[0])))
    return send_handoff(request, targets)


def send_handoff(request: AlertDeliveryRequest, targets: Sequence[HandoffTarget]) -> int:
    """How many destinations were sent to. Raises like a routed delivery, so the activity retries,
    and the thread claims skip a destination already sent to."""
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not targets:
        return 0
    still_firing = {
        (grouping_key, started_at)
        for grouping_key, started_at in PlatformAlert.objects.for_team(request.team_id)
        .filter(configuration_id=request.configuration_id, state=PlatformAlertState.FIRING)
        .values_list("grouping_key", "firing_started_at")
    }
    current = destination_handoff.current_addresses(
        request.team_id, request.configuration_id, {target.send.grouping_key for target in targets}
    )
    if current is None and any(target.send.gained for target in targets):
        # Unreadable flags would read as no routed receivers and drop every routed trigger for good.
        raise DeliveryError("Could not read whether this team routes alerts.")
    targets = [target for target in targets if _still_owed(target, current, still_firing)]
    announced = opening_transitions(
        request.team_id,
        request.configuration_id,
        source=request.source,
        episodes={target.send.grouping_key: target.send.episode_started_at for target in targets},
    )
    if announced is None:
        return 0
    announced = replace(announced, rule=rule_metadata(request.team_id, request.configuration_id))
    opening = {transition.grouping_key: transition for transition in announced.transitions}

    thread_store = DatabaseThreadStore(request.team_id)
    project = MessageLink(label=team.name, url=absolute_uri(f"/project/{team.id}"))
    tally = SendTally()
    for target in targets:
        transition = opening.get(target.send.grouping_key)
        transport_class = _TRANSPORTS.get(target.data.get("type"))
        if transition is None or transport_class is None or target.data.get("type") not in INCIDENT_DESTINATION_TYPES:
            continue
        if target.send.gained and delivery_holds.blocks_delivery(
            request.team_id, request.configuration_id, transition.evaluation_key
        ):
            # The firing's own trigger is held or suppressed, so no destination pages for it yet.
            continue
        action = IncidentAction.TRIGGER if target.send.gained else IncidentAction.RESOLVE
        with tally.attempt():
            deliver(
                transport=transport_class(),
                thread_store=thread_store,
                team_id=request.team_id,
                configuration_id=request.configuration_id,
                evaluation_key=request.evaluation_key,
                target=target.data,
                destination_id=target.send.destination_id,
                announcement=replace(announced, transitions=(transition,)),
                incident_action=action,
                source_alert_url=request.source_alert_url,
                source_incident_key=source_incident_key(request.destination_alert_id),
                project=project,
            )
    tally.raise_failures("handoff send")
    logger.info(
        "alerts_platform_handoff_delivered",
        configuration_id=request.configuration_id,
        evaluation_key=request.evaluation_key,
        sent=tally.sent,
    )
    return tally.sent


def _still_owed(
    target: HandoffTarget,
    current: dict[str, frozenset[str]] | None,
    still_firing: set[tuple[str, datetime | None]],
) -> bool:
    """Checked again when the send runs, because a later edit may have moved the firing back, and a
    stale send would undo it."""
    firing = (target.send.grouping_key, target.send.episode_started_at) in still_firing
    here = current is not None and destination_handoff.address(target.data) in current.get(
        target.send.grouping_key, frozenset()
    )
    if target.send.gained:
        # A firing that ended since sent its resolve to the destinations of that moment, so a trigger
        # now would open an incident nothing closes.
        return firing and here
    # Held back only while this same firing is still open at the destination. Once it ended, the
    # resolve went to wherever it was then, which may not have been here.
    return not (firing and here)
