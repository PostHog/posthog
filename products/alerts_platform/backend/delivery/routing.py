"""Sends an evaluation's messages to the team-wide receivers whose routes match the alert.

A path beside the alert's own destinations, not part of it. It reads nothing they read and
raises nothing, so a route can never cost an alert's own destinations their message.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Final

import structlog

from posthog.models import Team

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.delivery.thread_store import ThreadStore
from products.alerts_platform.backend.delivery.transport import DeliveryTransport
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    DestinationType,
    EvaluationAnnouncement,
    MessageLink,
)
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.alert_routes import routed_receivers
from products.alerts_platform.backend.models import PlatformAlertConfiguration

logger = structlog.get_logger(__name__)

ROUTING_FLAG: Final = "platform-alerts-routing"


def deliver_routes(
    *,
    request: AlertDeliveryRequest,
    announced: EvaluationAnnouncement,
    team: Team,
    thread_store: ThreadStore,
    project: MessageLink,
    transports: Mapping[DestinationType, type[DeliveryTransport]],
) -> int:
    """How many receivers were sent to. Messages only: an incident manager needs its trigger and
    resolve paired, which the source decides from the alert's own destinations."""
    if not request.owned_by_platform or not request.sends_messages:
        return 0
    try:
        if not team_flag_enabled(ROUTING_FLAG, team):
            return 0
        labels = (
            PlatformAlertConfiguration.objects.for_team(request.team_id)
            .filter(id=request.configuration_id)
            .values_list("labels", flat=True)
            .first()
        )
        receivers = routed_receivers(team_id=request.team_id, labels=labels or {})
    except Exception:
        logger.warning("alerts_platform_routing_lookup_failed", team_id=request.team_id, exc_info=True)
        return 0

    sent = 0
    for receiver in receivers:
        transport_class = transports.get(receiver.data["type"])
        if transport_class is None or receiver.data["type"] in INCIDENT_DESTINATION_TYPES:
            continue
        transitions = tuple(
            transition
            for transition in announced.transitions
            if transition.kind.value in request.event_ids_by_kind and transition.kind in receiver.event_kinds
        )
        if not transitions:
            continue
        try:
            deliver(
                transport=transport_class(),
                thread_store=thread_store,
                team_id=request.team_id,
                configuration_id=request.configuration_id,
                evaluation_key=request.evaluation_key,
                target=receiver.data,
                destination_id=str(receiver.id),
                announcement=replace(announced, transitions=transitions, overflowed=0),
                source_alert_url=request.source_alert_url,
                project=project,
            )
        except Exception as error:
            # Named by class only, because an exception's text can carry a credential URL.
            logger.warning(
                "alerts_platform_routed_delivery_failed",
                team_id=request.team_id,
                receiver_id=str(receiver.id),
                error=type(error).__name__,
            )
        else:
            sent += 1
    return sent
