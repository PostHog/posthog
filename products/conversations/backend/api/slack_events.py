"""Slack events endpoint for SupportHog app."""

import json
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.services.region_routing import (
    capture_replayable_request,
    is_primary_region,
    proxy_to_secondary_region,
)
from products.conversations.backend.support_slack import team_exists_for_slack_workspace, validate_support_request
from products.conversations.backend.tasks import process_supporthog_event, replay_supporthog_event_to_secondary_region

logger = structlog.get_logger(__name__)

# Event types we handle for support tickets
SUPPORT_EVENT_TYPES = [
    "app_mention",
    "message",
    "reaction_added",
    "member_joined_channel",
    "member_left_channel",
]


def _route_event_to_relevant_region(request: HttpRequest, data: dict) -> None:
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

    if inner_event_type not in SUPPORT_EVENT_TYPES:
        return

    team_exists = team_exists_for_slack_workspace(slack_team_id) if slack_team_id else False

    if team_exists and not (settings.DEBUG and is_primary_region(request)):
        cast(Any, process_supporthog_event).delay(event=event, slack_team_id=slack_team_id, event_id=event_id)
    elif is_primary_region(request):
        if not proxy_to_secondary_region(request, log_prefix="supporthog"):
            _schedule_secondary_region_replay(request)
    else:
        logger.warning("supporthog_no_team_any_region", slack_team_id=slack_team_id)


def _schedule_secondary_region_replay(request: HttpRequest) -> None:
    """Hand a failed inline forward to a task that keeps trying.

    Without this the webhook is gone, and with it whatever the customer said in Slack.
    """
    snapshot = capture_replayable_request(request)
    if snapshot is None:
        return
    cast(Any, replay_supporthog_event_to_secondary_region).delay(snapshot=snapshot, log_prefix="supporthog")


@csrf_exempt
def supporthog_event_handler(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Slack events for SupportHog app.

    This endpoint handles:
    - URL verification challenges from Slack
    - Event callbacks (message, app_mention, reaction_added)

    Regional routing: EU is the primary region. If the workspace isn't found
    locally, the request is proxied to the secondary region (US).
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

    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        # Slack retries when we answer slowly, which is when an event is most at risk of being
        # lost, so these are worth taking. `event_id` is what makes that safe: the processing
        # task dedupes on it, and that entry outlives the 5-minute signature window a retry has
        # to arrive in. With no id to dedupe against, a retry would double-post.
        if not isinstance(data.get("event_id"), str):
            logger.info("supporthog_event_retry_skipped", retry_num=retry_num)
            return HttpResponse(status=200)
        logger.info(
            "supporthog_event_retry_accepted",
            retry_num=retry_num,
            retry_reason=request.headers.get("X-Slack-Retry-Reason"),
        )

    logger.info("supporthog_event_received", event_type=data.get("type"))

    event_type = data.get("type")

    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("supporthog_url_verification", challenge=challenge[:20] + "...")
        return JsonResponse({"challenge": challenge})

    if event_type == "event_callback":
        _route_event_to_relevant_region(request, data)
        return HttpResponse(status=202)

    return HttpResponse(status=200)
