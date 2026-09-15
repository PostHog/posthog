"""Slack events endpoint for SupportHog app."""

import json
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.models import ConversationInboundEventSource
from products.conversations.backend.services.inbound_events import (
    accept_inbound_event,
    slack_events_source_id,
    slack_retry_metadata,
)
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.support_slack import team_for_slack_workspace, validate_support_request
from products.conversations.backend.tasks.slack import wake_inbound_event

logger = structlog.get_logger(__name__)

# Event types we handle for support tickets
SUPPORT_EVENT_TYPES = [
    "app_mention",
    "message",
    "reaction_added",
    "member_joined_channel",
    "member_left_channel",
]


def _accept_event_callback(request: HttpRequest, data: dict[str, Any]) -> HttpResponse:
    raw_event = data.get("event")
    event: dict[str, Any] = raw_event if isinstance(raw_event, dict) else {}
    slack_team_id = data.get("team_id", "") if isinstance(data.get("team_id"), str) else ""
    inner_event_type = event.get("type")
    retry_num, retry_reason = slack_retry_metadata(request)

    logger.info(
        "supporthog_event_callback",
        inner_event_type=inner_event_type,
        slack_team_id=slack_team_id,
        channel=event.get("channel"),
        retry_num=retry_num,
    )

    if inner_event_type not in SUPPORT_EVENT_TYPES:
        return HttpResponse(status=202)

    team = team_for_slack_workspace(slack_team_id) if slack_team_id else None

    if team is not None and not (settings.DEBUG and is_primary_region(request)):
        event_id = data.get("event_id") if isinstance(data.get("event_id"), str) else None
        accept_inbound_event(
            team=team,
            source=ConversationInboundEventSource.SLACK_EVENTS,
            source_id=slack_events_source_id(event_id=event_id, signed_body=request.body),
            provider_account_id=slack_team_id,
            payload=data,
            provider_retry_num=retry_num,
            provider_retry_reason=retry_reason,
            wake=wake_inbound_event,
        )
        return HttpResponse(status=202)

    if is_primary_region(request):
        if not proxy_to_secondary_region(request, log_prefix="supporthog"):
            return HttpResponse("Failed to reach owning region", status=502)
        return HttpResponse(status=202)

    logger.warning("supporthog_no_team_any_region", slack_team_id=slack_team_id)
    return HttpResponse(status=202)


@csrf_exempt
def supporthog_event_handler(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Slack events for SupportHog app.

    This endpoint handles:
    - URL verification challenges from Slack
    - Event callbacks (message, app_mention, reaction_added)

    Regional routing: EU is the primary region. If the workspace isn't found
    locally, the request is proxied to the secondary region (US).
    A 2xx means the owning region's Postgres receipt committed, not that a
    worker has processed the callback.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        validate_support_request(request)
    except SlackIntegrationError as e:
        logger.warning("supporthog_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)
    if not isinstance(data, dict):
        return HttpResponse("Invalid JSON", status=400)

    logger.info("supporthog_event_received", event_type=data.get("type"))

    event_type = data.get("type")

    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("supporthog_url_verification", challenge=challenge[:20] + "...")
        return JsonResponse({"challenge": challenge})

    if event_type == "event_callback":
        return _accept_event_callback(request, data)

    return HttpResponse(status=200)
