"""GitHub App deliveries for the Conversations GitHub Issues channel.

Two entry points, both reached from the facade after ingress verified the signature and parsed
the body: ``github_delivery_ownership`` answers which region holds the delivery's installation,
and ``accept_github_event`` hands the delivery to the Celery pipeline. No HTTP in here — ingress
owns the request, the receipt, and the forward to the region that owns the installation.
"""

import json
import hashlib
from typing import Any, cast

from django.db import InterfaceError, OperationalError

import structlog

from posthog.github.installations import installation_id
from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.database import (
    bounded_statement_timeout,
    is_connection_failure,
    is_statement_timeout,
    read_with_reconnect,
)
from posthog.models.integration import Integration

from products.conversations.backend.tasks.github import process_github_event

logger = structlog.get_logger(__name__)

# The event types this product consumes, and so the only ones it can answer ownership for.
_CONSUMED_EVENT_TYPES = frozenset({"issues", "issue_comment"})

# The lookup runs inside the request, before dispatch, so it draws on the delivery's wall clock.
_INSTALLATION_LOOKUP_TIMEOUT_MS = 800


def _payload_delivery_id(data: dict[str, Any]) -> str:
    """A stable id for a delivery GitHub sent no `X-GitHub-Delivery` for.

    The Celery task keys its own idempotency on this, so an empty string would collapse every
    header-less delivery onto one key. GitHub always sends the header in practice.
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


def _installation_integrations(external_id: str) -> list[Integration]:
    with bounded_statement_timeout(_INSTALLATION_LOOKUP_TIMEOUT_MS, models=[Integration]):
        return list(
            Integration.objects.filter(kind="github", integration_id=external_id).select_related("team").order_by("id")
        )


def _team_for_github_installation(external_id: str) -> tuple[int | None, bool]:
    """Resolve team ID from a GitHub App installation ID.

    Returns (team_id, github_enabled). team_id is None if no team has this
    installation connected for conversations.

    Multiple teams can share the same GitHub App installation ID (the unique
    constraint is per-team). We iterate all matches and only accept the one
    whose conversations_settings.github_integration_id explicitly points back
    to the Integration row, ensuring deterministic routing.

    A dropped connection gets one more attempt on a fresh one, because the read never ran. A
    cancelled statement raises, because a lookup that never finished is not an answer. Each
    caller decides what to do with it.
    """
    integrations = read_with_reconnect(lambda: _installation_integrations(external_id), models=[Integration])

    for integration in integrations:
        settings_dict = integration.team.conversations_settings or {}
        if not settings_dict.get("github_enabled", False):
            continue
        expected_integration_id = settings_dict.get("github_integration_id")
        if expected_integration_id is not None and expected_integration_id != integration.id:
            continue
        if expected_integration_id is None:
            continue
        return integration.team_id, True

    return None, False


def github_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the team this delivery's installation is connected to.

    An installation this region does not own is `ELSEWHERE` rather than undecided, so the
    delivery reaches the other region: it is the only one that can tell an installation it holds
    from one nobody holds, and GitHub never redelivers an event it got a receipt for.
    """
    if delivery.event_type not in _CONSUMED_EVENT_TYPES:
        return DeliveryOwnership.UNDECIDED
    external_id = installation_id(dict(delivery.payload))
    if external_id is None:
        return DeliveryOwnership.UNDECIDED

    try:
        team_id, github_enabled = _team_for_github_installation(external_id)
    except (OperationalError, InterfaceError) as error:
        if is_statement_timeout(error):
            logger.warning("github_issues_webhook_installation_lookup_timed_out", installation_id=external_id)
        elif is_connection_failure(error):
            logger.warning("github_issues_webhook_installation_lookup_lost_connection", installation_id=external_id)
        else:
            raise
        # Elsewhere rather than an error: the two answers here are "this region owns it" and
        # "somebody else does", and a lookup that never answered has not shown ownership here.
        # Raising answers undecided instead, which forwards nothing on a delivery GitHub has
        # already been receipted for and never sends again.
        return DeliveryOwnership.ELSEWHERE

    if team_id and github_enabled:
        return DeliveryOwnership.LOCAL
    return DeliveryOwnership.ELSEWHERE


def accept_github_event(delivery: WebhookDelivery) -> None:
    """Route a verified GitHub delivery to the conversations Celery pipeline."""
    payload = dict(delivery.payload)
    external_id = installation_id(payload)
    if external_id is None:
        logger.warning("github_issues_webhook_no_installation")
        return

    # Unguarded on purpose: a timed-out lookup fails the delivery, so the dispatcher releases the
    # dedup mark and a redelivery reaches this consumer instead of the event being lost.
    team_id, github_enabled = _team_for_github_installation(external_id)
    if not (team_id and github_enabled):
        # Quiet on purpose: ingress reports a delivery no region here owns, off the ownership
        # answer this module gave it before dispatch.
        return

    cast(Any, process_github_event).delay(
        event_type=delivery.event_type,
        action=payload.get("action", ""),
        payload=payload,
        delivery_id=delivery.delivery_id or _payload_delivery_id(payload),
        team_id=team_id,
        repo=payload.get("repository", {}).get("full_name", ""),
    )
