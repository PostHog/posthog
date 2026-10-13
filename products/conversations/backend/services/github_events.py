"""GitHub App deliveries for the Conversations GitHub Issues channel.

One entry point, reached from the facade after ingress verified the signature and parsed the
body: ``accept_github_event`` hands the delivery to the Celery pipeline. No HTTP in here,
because ingress owns the request and the receipt.
"""

import json
import hashlib
from typing import Any, cast

import structlog

from posthog.github.installations import installation_id
from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.integration import Integration

from products.conversations.backend.tasks.github import process_github_event

logger = structlog.get_logger(__name__)

# The lookup runs inside the request, before dispatch, so it draws on the delivery's wall clock.
_INSTALLATION_LOOKUP_TIMEOUT_MS = 800


def _payload_delivery_id(data: dict[str, Any]) -> str:
    """A stable id for a delivery GitHub sent no `X-GitHub-Delivery` for.

    The Celery task keys its own idempotency on this, so an empty string would collapse every
    header-less delivery onto one key. GitHub always sends the header in practice.
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


def _team_for_github_installation(external_id: str) -> tuple[int | None, bool]:
    """Resolve team ID from a GitHub App installation ID.

    Returns (team_id, github_enabled). team_id is None if no team has this
    installation connected for conversations.

    Multiple teams can share the same GitHub App installation ID (the unique
    constraint is per-team). We iterate all matches and only accept the one
    whose conversations_settings.github_integration_id explicitly points back
    to the Integration row, ensuring deterministic routing.

    A cancelled statement raises, because a lookup that never finished is not an answer.
    """
    with bounded_statement_timeout(_INSTALLATION_LOOKUP_TIMEOUT_MS, models=[Integration]):
        integrations = list(
            Integration.objects.filter(kind="github", integration_id=external_id).select_related("team").order_by("id")
        )

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
        # Quiet on purpose, because this is the normal case. Each region runs its own GitHub App,
        # so this endpoint only ever receives its own installations, and an installation no team
        # here has connected simply has the GitHub Issues channel off.
        return

    cast(Any, process_github_event).delay(
        event_type=delivery.event_type,
        action=payload.get("action", ""),
        payload=payload,
        delivery_id=delivery.delivery_id or _payload_delivery_id(payload),
        team_id=team_id,
        repo=payload.get("repository", {}).get("full_name", ""),
    )
