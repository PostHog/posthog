"""Slack events endpoint for SupportHog app."""

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError

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
        SlackIntegration.validate_request(request)
    except SlackIntegrationError as e:
        logger.warning("supporthog_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    # Check for retry to avoid duplicate processing
    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("supporthog_event_retry_skipped", retry_num=retry_num)
        return HttpResponse(status=200)

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
            _handle_support_event(event, slack_team_id)

        return HttpResponse(status=202)

    return HttpResponse(status=200)


def _handle_support_event(event: dict, slack_team_id: str) -> None:
    """Route event to appropriate support handler."""
    from products.conversations.backend.slack import (
        handle_support_mention,
        handle_support_message,
        handle_support_reaction,
    )

    # Find the Slack integration for this workspace
    integration = Integration.objects.filter(kind="slack", integration_id=slack_team_id).select_related("team").first()

    if not integration:
        logger.warning("supporthog_no_integration", slack_team_id=slack_team_id)
        return

    # Check if support is configured for this team
    team = integration.team
    support_settings = team.conversations_settings or {}

    if not support_settings.get("slack_integration_id"):
        logger.info(
            "supporthog_support_not_configured",
            team_id=team.id,
            slack_team_id=slack_team_id,
        )
        return

    event_type = event.get("type")

    try:
        if event_type == "message":
            handle_support_message(event, integration)
        elif event_type == "app_mention":
            handle_support_mention(event, integration)
        elif event_type == "reaction_added":
            handle_support_reaction(event, integration)
    except Exception as e:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event_type,
            error=str(e),
        )
