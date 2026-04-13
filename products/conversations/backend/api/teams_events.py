"""Microsoft Teams Bot Framework messaging endpoint for SupportHog."""

import json
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.team import Team

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.support_teams import validate_teams_request
from products.conversations.backend.tasks import process_teams_event

logger = structlog.get_logger(__name__)

TEAMS_MESSAGE_TYPES = {"message"}


def _team_for_teams_tenant(tenant_id: str) -> Team | None:
    config = (
        TeamConversationsTeamsConfig.objects.filter(teams_tenant_id=tenant_id, teams_graph_access_token__isnull=False)
        .select_related("team")
        .first()
    )
    return config.team if config else None


def _route_activity_to_relevant_region(request: HttpRequest, activity: dict) -> None:
    activity_type = activity.get("type", "")
    channel_data = activity.get("channelData") or {}
    tenant_id = (channel_data.get("tenant") or {}).get("id", "")
    activity_id = activity.get("id", "")

    logger.info(
        "supporthog_teams_activity",
        activity_type=activity_type,
        tenant_id=tenant_id,
        channel_id=channel_data.get("channel", {}).get("id") if isinstance(channel_data.get("channel"), dict) else None,
    )

    if activity_type not in TEAMS_MESSAGE_TYPES:
        return

    team = _team_for_teams_tenant(tenant_id) if tenant_id else None

    if team and not (settings.DEBUG and is_primary_region(request)):
        cast(Any, process_teams_event).delay(
            activity=activity,
            tenant_id=tenant_id,
            activity_id=activity_id,
        )
    elif is_primary_region(request):
        proxy_to_secondary_region(request, log_prefix="supporthog_teams")
    else:
        logger.warning("supporthog_teams_no_team_any_region", tenant_id=tenant_id)


@csrf_exempt
def teams_event_handler(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Bot Framework activities from Microsoft Teams.

    Validates the JWT bearer token, routes to the correct region,
    and dispatches message activities to a Celery task.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        validate_teams_request(request)
    except ValueError as e:
        logger.warning("supporthog_teams_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        activity = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    activity_type = activity.get("type", "")
    logger.info("supporthog_teams_event_received", activity_type=activity_type)

    if activity_type == "message":
        _route_activity_to_relevant_region(request, activity)
        return HttpResponse(status=202)

    # Acknowledge other activity types (installationUpdate, conversationUpdate, etc.)
    return HttpResponse(status=200)
