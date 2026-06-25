"""Slack interactivity endpoint for the SupportHog app.

Receives button clicks from the opt-in "open a ticket?" ephemeral prompt
(``slack_confirm_before_ticket``). The events endpoint posts the prompt; this
endpoint handles the click and creates — or skips — the ticket.
"""

import json
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.models import TeamConversationsSlackConfig
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.support_slack import validate_support_request
from products.conversations.backend.tasks import process_supporthog_interactivity

logger = structlog.get_logger(__name__)


def _team_exists_for_slack_workspace(slack_team_id: str) -> bool:
    return TeamConversationsSlackConfig.objects.filter(
        slack_team_id=slack_team_id, slack_bot_token__isnull=False
    ).exists()


@csrf_exempt
def supporthog_interactivity_handler(request: HttpRequest) -> HttpResponse:
    """Handle Slack interactive button clicks for SupportHog.

    Regional routing matches the events endpoint: EU is the primary region. If the
    workspace isn't found locally, the request is proxied to the secondary region (US).
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        validate_support_request(request)
    except SlackIntegrationError as e:
        logger.warning("supporthog_interactivity_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except (json.JSONDecodeError, TypeError):
        return HttpResponse("Invalid JSON", status=400)

    slack_team_id = (payload.get("team") or {}).get("id", "")
    if not slack_team_id:
        return HttpResponse(status=200)

    logger.info("supporthog_interactivity_received", payload_type=payload.get("type"), slack_team_id=slack_team_id)

    if _team_exists_for_slack_workspace(slack_team_id) and not (settings.DEBUG and is_primary_region(request)):
        cast(Any, process_supporthog_interactivity).delay(payload=payload, slack_team_id=slack_team_id)
    elif is_primary_region(request):
        proxy_to_secondary_region(request, log_prefix="supporthog_interactivity")
    else:
        logger.warning("supporthog_interactivity_no_team_any_region", slack_team_id=slack_team_id)

    return HttpResponse(status=200)
