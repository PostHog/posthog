"""Slack events endpoint for SupportHog app."""

import json

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError
from posthog.models.team import Team

from products.conversations.backend.support_slack import validate_support_request

logger = structlog.get_logger(__name__)

# Event types we handle for support tickets
SUPPORT_EVENT_TYPES = ["app_mention", "message", "reaction_added"]
EVENT_IDEMPOTENCY_TTL_SECONDS = 15 * 60
EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"


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
        event_id = data.get("event_id")
        if isinstance(event_id, str) and event_id and _is_duplicate_event(event_id):
            logger.info("supporthog_event_duplicate_skipped", event_id=event_id)
            return HttpResponse(status=200)

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


def _is_duplicate_event(event_id: str) -> bool:
    key = f"{EVENT_IDEMPOTENCY_KEY_PREFIX}{event_id}"
    return not cache.add(key, True, timeout=EVENT_IDEMPOTENCY_TTL_SECONDS)


def _handle_support_event(event: dict, slack_team_id: str) -> None:
    """Route event to appropriate support handler."""
    from products.conversations.backend.slack import (
        handle_support_mention,
        handle_support_message,
        handle_support_reaction,
    )

    # Find team with SupportHog configured for this Slack workspace
    team = Team.objects.filter(conversations_settings__slack_team_id=slack_team_id).first()
    if not team:
        logger.warning("supporthog_no_team", slack_team_id=slack_team_id)
        return

    # Check if support is configured for this team
    support_settings = team.conversations_settings or {}

    if not support_settings.get("slack_enabled"):
        logger.info(
            "supporthog_support_not_configured",
            team_id=team.id,
            slack_team_id=slack_team_id,
        )
        return

    event_type = event.get("type")

    try:
        if event_type == "message":
            handle_support_message(event, team, slack_team_id)
        elif event_type == "app_mention":
            handle_support_mention(event, team, slack_team_id)
        elif event_type == "reaction_added":
            handle_support_reaction(event, team, slack_team_id)
    except Exception as e:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event_type,
            error=str(e),
        )
