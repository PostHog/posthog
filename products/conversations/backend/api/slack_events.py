"""Slack events endpoint for SupportHog app."""

import json
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from requests import RequestException

from posthog.models.integration import SlackIntegrationError
from posthog.models.team import Team
from posthog.security.outbound_proxy import external_requests

from products.conversations.backend.models import TeamConversationsSlackConfig
from products.conversations.backend.support_slack import validate_support_request
from products.conversations.backend.tasks import process_supporthog_event

logger = structlog.get_logger(__name__)

# Event types we handle for support tickets
SUPPORT_EVENT_TYPES = ["app_mention", "message", "reaction_added"]

# Regional routing: EU is the primary region (Slack Request URL points here).
# If EU doesn't own the workspace, it proxies the event to US.
SUPPORTHOG_PRIMARY_REGION_DOMAIN = "eu.posthog.com"
SUPPORTHOG_SECONDARY_REGION_DOMAIN = "us.posthog.com"

if settings.DEBUG:
    SUPPORTHOG_PRIMARY_REGION_DOMAIN = urlparse(settings.SITE_URL).netloc
    SUPPORTHOG_SECONDARY_REGION_DOMAIN = "localhost:8000"


def _team_for_slack_workspace(slack_team_id: str) -> Team | None:
    config = (
        TeamConversationsSlackConfig.objects.filter(slack_team_id=slack_team_id, slack_bot_token__isnull=False)
        .select_related("team")
        .first()
    )
    return config.team if config else None


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

    team = _team_for_slack_workspace(slack_team_id) if slack_team_id else None

    if team and not (settings.DEBUG and request.get_host() == SUPPORTHOG_PRIMARY_REGION_DOMAIN):
        cast(Any, process_supporthog_event).delay(event=event, slack_team_id=slack_team_id, event_id=event_id)
    elif request.get_host() == SUPPORTHOG_PRIMARY_REGION_DOMAIN:
        _proxy_to_secondary_region(request)
    else:
        logger.warning("supporthog_no_team_any_region", slack_team_id=slack_team_id)


def _proxy_to_secondary_region(request: HttpRequest) -> None:
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=SUPPORTHOG_SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    try:
        response = external_requests.request(
            method=request.method or "POST",
            url=target_url,
            headers=headers,
            params=dict(request.GET.lists()) if request.GET else None,
            data=request.body or None,
            timeout=3,
        )
        logger.info(
            "supporthog_proxy_to_secondary_region",
            target_url=target_url,
            status_code=response.status_code,
        )
    except RequestException as exc:
        logger.exception("supporthog_proxy_to_secondary_region_failed", error=str(exc), target_url=target_url)


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

    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("supporthog_url_verification", challenge=challenge[:20] + "...")
        return JsonResponse({"challenge": challenge})

    if event_type == "event_callback":
        _route_event_to_relevant_region(request, data)
        return HttpResponse(status=202)

    return HttpResponse(status=200)
