"""Slack deliveries for the SupportHog app, from the Events API and from interactive components.

Three entry points, all reached from the facade after ingress verified the signature and parsed
the body: ``slack_delivery_ownership`` answers which region holds the workspace the delivery is
about, and ``accept_slack_event`` and ``accept_slack_interactivity`` write the inbound receipt and
wake its worker. No HTTP in here -- ingress owns the request, the receipt and the forward to the
region that owns the workspace.

Both Slack endpoints live here because they answer ownership the same way: each carries the
workspace id in the delivery context, and one bounded lookup resolves it for both.
"""

import json
from typing import Any

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.team import Team

from products.conversations.backend.models import ConversationInboundEventSource, TeamConversationsSlackConfig
from products.conversations.backend.services.inbound_events import (
    accept_inbound_event,
    slack_events_source_id,
    slack_interactivity_source_id,
    slack_retry_metadata_from_values,
)
from products.conversations.backend.support_slack import team_for_slack_workspace
from products.conversations.backend.tasks.slack import wake_inbound_event

# The lookup runs inside the request, before dispatch, so it draws on the delivery's wall clock.
_WORKSPACE_LOOKUP_TIMEOUT_MS = 800


def _team_for_workspace(slack_team_id: str) -> Team | None:
    """The team SupportHog is connected to for this workspace, or None when no team here is.

    A cancelled statement raises, because a lookup that never finished is not an answer. Both
    callers let it out rather than guessing past it.
    """
    with bounded_statement_timeout(_WORKSPACE_LOOKUP_TIMEOUT_MS, models=[TeamConversationsSlackConfig]):
        return team_for_slack_workspace(slack_team_id)


def slack_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the team the delivery's Slack workspace is connected to.

    A workspace this region does not know is `ELSEWHERE` rather than undecided, so the delivery
    reaches the other region: it is the only one that can tell a workspace it holds from one
    nobody holds. A lookup that raised, the statement timeout included, has shown no such thing,
    so it propagates rather than answering `ELSEWHERE`: the delivery carries the workspace's
    support messages, and a workspace this region owns must not have them forwarded across the
    region boundary on a guess. A raised lookup asks Slack to redeliver instead.
    """
    slack_team_id = delivery.context.get("slack_team_id", "")
    if not slack_team_id:
        return DeliveryOwnership.UNDECIDED

    team = _team_for_workspace(slack_team_id)
    return DeliveryOwnership.LOCAL if team is not None else DeliveryOwnership.ELSEWHERE


def _accept_delivery(
    delivery: WebhookDelivery,
    *,
    source: ConversationInboundEventSource,
    payload: dict[str, Any],
    source_id: str,
) -> None:
    """Write the inbound receipt for a verified Slack delivery and wake its worker."""
    slack_team_id = delivery.context.get("slack_team_id", "")
    # Unguarded on purpose: a timed-out lookup fails the delivery, so the dispatcher releases the
    # dedup mark and Slack's redelivery reaches this consumer instead of the delivery being lost.
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
        source=source,
        source_id=source_id,
        provider_account_id=slack_team_id,
        payload=payload,
        provider_retry_num=retry_num,
        provider_retry_reason=retry_reason,
        wake=wake_inbound_event,
    )


def accept_slack_event(delivery: WebhookDelivery) -> None:
    """Record a verified Slack event against the workspace's team and wake its worker."""
    payload: dict[str, Any] = dict(delivery.payload)
    _accept_delivery(
        delivery,
        source=ConversationInboundEventSource.SLACK_EVENTS,
        payload=payload,
        # A delivery carries no raw body, so an event without an id falls back to a hash of the
        # parsed payload rather than of the signed bytes.
        source_id=slack_events_source_id(
            event_id=delivery.delivery_id,
            signed_body=json.dumps(payload, sort_keys=True).encode("utf-8"),
        ),
    )


def accept_slack_interactivity(delivery: WebhookDelivery) -> None:
    """Record a verified Slack interactive payload against the workspace's team and wake its worker."""
    payload: dict[str, Any] = dict(delivery.payload)
    # The signed `payload` field, which the incarnation carries on the context so the source id
    # hashes the bytes Slack signed rather than a re-serialization of the parsed mapping.
    raw_payload = delivery.context.get("raw_payload", "")
    _accept_delivery(
        delivery,
        source=ConversationInboundEventSource.SLACK_INTERACTIVITY,
        payload=payload,
        source_id=slack_interactivity_source_id(payload=payload, signed_body=raw_payload.encode("utf-8")),
    )
