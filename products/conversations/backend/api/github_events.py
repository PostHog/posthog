"""GitHub event dispatch for Conversations GitHub Issues channel.

The entry point is ``dispatch_github_event``, called from the GitHub App
webhook fan-out in ``posthog.urls.github_webhook`` after signature verification
and JSON parsing.
"""

import hashlib
from typing import Any, cast

from django.http import HttpRequest, HttpResponse

import structlog

from posthog.models.integration import Integration

from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.tasks import process_github_event

logger = structlog.get_logger(__name__)


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


def dispatch_github_event(request: HttpRequest, event_type: str, data: dict[str, Any]) -> HttpResponse:
    """Route a pre-verified GitHub event to the conversations Celery pipeline.

    Called from ``posthog.urls.github_webhook`` after signature verification
    and JSON parsing are already done.
    """
    installation_id = str(data.get("installation", {}).get("id", ""))
    if not installation_id:
        logger.warning("github_issues_webhook_no_installation")
        return HttpResponse(status=200)

    team_id, github_enabled = _team_for_github_installation(installation_id)

    if team_id and github_enabled:
        repo_full_name = data.get("repository", {}).get("full_name", "")
        action = data.get("action", "")
        delivery_id = request.headers.get("X-GitHub-Delivery") or hashlib.sha256(request.body).hexdigest()[:32]

        cast(Any, process_github_event).delay(
            event_type=event_type,
            action=action,
            payload=data,
            delivery_id=delivery_id,
            team_id=team_id,
            repo=repo_full_name,
        )
        return HttpResponse(status=202)
    elif is_primary_region(request):
        proxy_to_secondary_region(request, log_prefix="github_issues")
        return HttpResponse(status=200)
    else:
        logger.warning(
            "github_issues_webhook_no_team",
            installation_id=installation_id,
        )
        return HttpResponse(status=200)
