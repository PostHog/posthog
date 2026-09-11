"""Slack interactivity endpoint for the SupportHog app.

Receives button clicks from the "open a ticket?" nudge prompt posted in channels
outside the configured support channels (``slack_nudge_enabled``, on by default).
The events endpoint posts the prompt; this endpoint handles the click and creates
— or skips — the ticket.
"""

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.models import ConversationInboundEventSource
from products.conversations.backend.services.inbound_events import (
    accept_inbound_event,
    slack_interactivity_source_id,
    slack_retry_metadata,
)
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.support_slack import team_for_slack_workspace, validate_support_request
from products.conversations.backend.tasks.slack import wake_inbound_event

logger = structlog.get_logger(__name__)


@csrf_exempt
def supporthog_interactivity_handler(request: HttpRequest) -> HttpResponse:
    """Handle Slack interactive button clicks for SupportHog.

    Regional routing matches the events endpoint: EU is the primary region. If the
    workspace isn't found locally, the request is proxied to the secondary region (US).
    A 2xx means the owning region's Postgres receipt committed, not that a worker has
    processed the click.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        validate_support_request(request)
    except SlackIntegrationError as e:
        logger.warning("supporthog_interactivity_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    # Hash the form `payload` field. request.body is already consumed after request.POST
    # on ASGI, and Slack retries send the same payload JSON.
    raw_payload = request.POST.get("payload", "{}")
    try:
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError):
        return HttpResponse("Invalid JSON", status=400)
    if not isinstance(payload, dict):
        return HttpResponse("Invalid payload", status=400)

    slack_team = payload.get("team")
    slack_team_id = slack_team.get("id", "") if isinstance(slack_team, dict) else ""
    if not slack_team_id:
        return HttpResponse(status=200)

    retry_num, retry_reason = slack_retry_metadata(request)
    logger.info(
        "supporthog_interactivity_received",
        payload_type=payload.get("type"),
        slack_team_id=slack_team_id,
        retry_num=retry_num,
    )

    team = team_for_slack_workspace(slack_team_id)
    if team is not None and not (settings.DEBUG and is_primary_region(request)):
        accept_inbound_event(
            team=team,
            source=ConversationInboundEventSource.SLACK_INTERACTIVITY,
            source_id=slack_interactivity_source_id(
                payload=payload,
                signed_body=(raw_payload or "").encode("utf-8"),
            ),
            provider_account_id=slack_team_id,
            payload=payload,
            provider_retry_num=retry_num,
            provider_retry_reason=retry_reason,
            wake=wake_inbound_event,
        )
        return HttpResponse(status=200)

    if is_primary_region(request):
        # Acking a failed proxy with 200 makes the click silently vanish — Slack shows the
        # clicker nothing and never resends. Surface the failure so Slack displays a
        # delivery error and the user knows to click again.
        if not proxy_to_secondary_region(request, log_prefix="supporthog_interactivity"):
            return HttpResponse("Failed to reach owning region", status=502)
        return HttpResponse(status=200)

    logger.warning("supporthog_interactivity_no_team_any_region", slack_team_id=slack_team_id)
    return HttpResponse(status=200)
