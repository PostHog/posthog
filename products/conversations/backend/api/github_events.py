"""GitHub event dispatch for Conversations GitHub Issues channel.

Two entry points, both reached after ingress verified the signature and parsed the body:
``dispatch_github_event`` is the registered webhook consumer, and
``proxy_github_event_to_owning_region`` runs ahead of the fan-out because forwarding a
delivery needs the signed bytes, which a consumer never sees.
"""

import json
import hashlib
from typing import Any, cast

from django.http import HttpRequest, HttpResponse

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration

from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.tasks.github import process_github_event

logger = structlog.get_logger(__name__)

# The event types this product consumes, and so the only ones worth forwarding to another region.
_PROXIED_EVENT_TYPES = frozenset({"issues", "issue_comment"})


def _payload_delivery_id(data: dict[str, Any]) -> str:
    """A stable id for a delivery GitHub sent no `X-GitHub-Delivery` for.

    The Celery task keys its own idempotency on this, so an empty string would collapse every
    header-less delivery onto one key. GitHub always sends the header in practice.
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


def _team_for_github_installation(installation_id: str) -> tuple[int | None, bool]:
    """Resolve team ID from a GitHub App installation ID.

    Returns (team_id, github_enabled). team_id is None if no team has this
    installation connected for conversations.

    Multiple teams can share the same GitHub App installation ID (the unique
    constraint is per-team). We iterate all matches and only accept the one
    whose conversations_settings.github_integration_id explicitly points back
    to the Integration row, ensuring deterministic routing.
    """
    integrations = (
        Integration.objects.filter(kind="github", integration_id=installation_id).select_related("team").order_by("id")
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


def dispatch_github_event(event_type: str, data: dict[str, Any], delivery_id: str | None) -> None:
    """Route a verified GitHub event to the conversations Celery pipeline."""
    installation_id = str(data.get("installation", {}).get("id", ""))
    if not installation_id:
        logger.warning("github_issues_webhook_no_installation")
        return

    team_id, github_enabled = _team_for_github_installation(installation_id)
    if not (team_id and github_enabled):
        # Quiet on purpose: the regional proxy runs first on these same event types and it is the
        # one that knows whether an unowned installation was forwarded or reached its last region.
        return

    cast(Any, process_github_event).delay(
        event_type=event_type,
        action=data.get("action", ""),
        payload=data,
        delivery_id=delivery_id or _payload_delivery_id(data),
        team_id=team_id,
        repo=data.get("repository", {}).get("full_name", ""),
    )


def proxy_github_event_to_owning_region(request: HttpRequest, payload: Any) -> HttpResponse | None:
    """Forward a delivery for an installation this region does not own to the secondary one.

    Runs before the fan-out and always answers ``None`` so the other consumers on this endpoint
    still run here, exactly as they did when this was the first handler in the chain. It cannot
    be a consumer: forwarding replays the signed bytes, and a consumer only sees the parsed body.
    It also reports an installation no region owns, because only this side of the split knows
    which region the delivery reached.
    """
    if request.headers.get("X-GitHub-Event") not in _PROXIED_EVENT_TYPES:
        return None
    if not isinstance(payload, dict):
        return None

    installation_id = str(payload.get("installation", {}).get("id", ""))
    if not installation_id:
        return None

    # Repeats the consumer's lookup rather than sharing it: the proxy decision is owed to the
    # request before dispatch starts, and the consumer runs per delivery with no request at all.
    try:
        team_id, github_enabled = _team_for_github_installation(installation_id)
    except Exception as error:
        # This runs outside the dispatcher's per-consumer isolation, so a database blip here would
        # answer GitHub a 500 instead of the receipt a verified delivery has already earned.
        logger.exception("github_issues_webhook_region_lookup_failed", installation_id=installation_id)
        capture_exception(error)
        return None

    if team_id and github_enabled:
        return None
    if is_primary_region(request):
        proxy_to_secondary_region(request, log_prefix="github_issues")
    else:
        logger.warning("github_issues_webhook_no_team", installation_id=installation_id)
    return None
