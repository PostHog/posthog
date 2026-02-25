"""Slack events endpoint for SupportHog app."""

import json
from typing import Any, cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.support_slack import validate_support_request
from products.conversations.backend.tasks import process_supporthog_event

logger = structlog.get_logger(__name__)

# Event types we handle for support tickets
SUPPORT_EVENT_TYPES = ["app_mention", "message", "reaction_added"]


@csrf_exempt
def supporthog_event_handler(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Slack events for SupportHog app.

    This endpoint handles:
    - URL verification challenges from Slack
    - Event callbacks (message, app_mention, reaction_added)
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    # Validate the request signature
    try:
        validate_support_request(request)
    except SlackIntegrationError as e:
        logger.warning("supporthog_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    logger.info("supporthog_event_received", event_type=data.get("type"))

    event_type = data.get("type")

    # Handle URL verification challenge
    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("supporthog_url_verification", challenge=challenge[:20] + "...")
        return JsonResponse({"challenge": challenge})

    # Handle event callbacks
    if event_type == "event_callback":
        event_id = data.get("event_id") if isinstance(data.get("event_id"), str) else None
        event = data.get("event", {})
        slack_team_id = data.get("team_id", "")
        inner_event_type = event.get("type")

        logger.info(
            "supporthog_event_callback",
            inner_event_type=inner_event_type,
            slack_team_id=slack_team_id,
            channel=event.get("channel"),
        )

        if inner_event_type in SUPPORT_EVENT_TYPES:
            cast(Any, process_supporthog_event).delay(event=event, slack_team_id=slack_team_id, event_id=event_id)

        return HttpResponse(status=202)

    return HttpResponse(status=200)
