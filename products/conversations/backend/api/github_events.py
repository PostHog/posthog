"""GitHub webhook endpoint for Conversations GitHub Issues channel."""

import hmac
import json
import hashlib
from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration

from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.tasks import process_github_event

logger = structlog.get_logger(__name__)

GITHUB_HANDLED_EVENTS = {"issues", "issue_comment"}


def _get_github_webhook_secret() -> str | None:
    secret = get_instance_setting("GITHUB_WEBHOOK_SECRET")
    return secret if secret else None


def _verify_github_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


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
        # Require explicit binding — skip if github_integration_id was never set
        if expected_integration_id is None:
            continue
        return integration.team_id, True

    return None, False


@csrf_exempt
def github_issues_webhook(request: HttpRequest) -> HttpResponse:
    """Handle incoming GitHub webhook events for the Issues channel.

    Verifies HMAC-SHA256 signature, resolves the team via installation ID,
    checks that the repo is monitored, and dispatches to a Celery task.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    secret = _get_github_webhook_secret()
    if not secret:
        logger.warning("github_issues_webhook_no_secret")
        return HttpResponse(status=503)

    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_github_signature(request.body, signature, secret):
        logger.warning("github_issues_webhook_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type not in GITHUB_HANDLED_EVENTS:
        return HttpResponse(status=200)

    try:
        data: dict[str, Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

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
