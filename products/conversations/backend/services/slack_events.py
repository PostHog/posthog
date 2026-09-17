"""Slack Events API deliveries for the SupportHog app.

Two entry points, both reached from the facade after ingress verified the signature and parsed
the envelope: ``slack_delivery_ownership`` answers which region holds the workspace the delivery
is about, and ``accept_slack_event`` writes the inbound receipt and wakes its worker. No HTTP in
here -- ingress owns the request, the receipt and the forward to the region that owns the
workspace.
"""

import json
from typing import Any

from django.db import OperationalError

import structlog

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.database import bounded_statement_timeout, is_statement_timeout
from posthog.models.team import Team

from products.conversations.backend.models import ConversationInboundEventSource, TeamConversationsSlackConfig
from products.conversations.backend.services.inbound_events import (
    accept_inbound_event,
    slack_events_source_id,
    slack_retry_metadata_from_values,
)
from products.conversations.backend.support_slack import team_for_slack_workspace
from products.conversations.backend.tasks.slack import wake_inbound_event

logger = structlog.get_logger(__name__)

# The lookup runs inside the request, before dispatch, so it draws on the delivery's wall clock.
_WORKSPACE_LOOKUP_TIMEOUT_MS = 800


def _team_for_workspace(slack_team_id: str) -> Team | None:
    """The team SupportHog is connected to for this workspace, or None when no team here is.

    A cancelled statement raises, because a lookup that never finished is not an answer. Each
    caller decides what to do with it.
    """
    with bounded_statement_timeout(_WORKSPACE_LOOKUP_TIMEOUT_MS, models=[TeamConversationsSlackConfig]):
        return team_for_slack_workspace(slack_team_id)


def slack_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the team the delivery's Slack workspace is connected to.

    A workspace this region does not know is `ELSEWHERE` rather than undecided, so the delivery
    reaches the other region: it is the only one that can tell a workspace it holds from one
    nobody holds. A lookup that timed out answers the same way, for the same reason.
    """
    slack_team_id = delivery.context.get("slack_team_id", "")
    if not slack_team_id:
        return DeliveryOwnership.UNDECIDED

    try:
        team = _team_for_workspace(slack_team_id)
    except OperationalError as error:
        if not is_statement_timeout(error):
            raise
        # Elsewhere rather than a failed lookup: a timeout has not shown ownership here, which
        # leaves the delivery in the same state as a workspace this region does not know, and the
        # other region can still answer it. A failed lookup asks Slack to redeliver instead.
        logger.warning("supporthog_event_workspace_lookup_timed_out", slack_team_id=slack_team_id)
        return DeliveryOwnership.ELSEWHERE

    return DeliveryOwnership.LOCAL if team is not None else DeliveryOwnership.ELSEWHERE


def accept_slack_event(delivery: WebhookDelivery) -> None:
    """Record a verified Slack event against the workspace's team and wake its worker."""
    payload: dict[str, Any] = dict(delivery.payload)
    slack_team_id = delivery.context.get("slack_team_id", "")
    # Unguarded on purpose: a timed-out lookup fails the delivery, so the dispatcher releases the
    # dedup mark and Slack's redelivery reaches this consumer instead of the event being lost.
    team = _team_for_workspace(slack_team_id) if slack_team_id else None
    if team is None:
        # Quiet on purpose: ingress reports a delivery no region here owns, off the ownership
        # answer this module gave it before dispatch.
        return

    retry_num, retry_reason = slack_retry_metadata_from_values(
        raw_retry_num=delivery.context.get("retry_num", ""),
        retry_reason=delivery.context.get("retry_reason", ""),
    )
    accept_inbound_event(
        team=team,
        source=ConversationInboundEventSource.SLACK_EVENTS,
        # A delivery carries no raw body, so an event without an id falls back to a hash of the
        # parsed payload rather than of the signed bytes.
        source_id=slack_events_source_id(
            event_id=delivery.delivery_id,
            signed_body=json.dumps(payload, sort_keys=True).encode("utf-8"),
        ),
        provider_account_id=slack_team_id,
        payload=payload,
        provider_retry_num=retry_num,
        provider_retry_reason=retry_reason,
        wake=wake_inbound_event,
    )
