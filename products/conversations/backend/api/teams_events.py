"""Microsoft Teams Bot Framework messaging endpoint for SupportHog."""

import json
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework.request import Request as DRFRequest

from posthog.models.team import Team
from posthog.rate_limit import TeamsEventWebhookThrottle

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region
from products.conversations.backend.support_teams import is_trusted_teams_service_url, validate_teams_request
from products.conversations.backend.tasks import process_teams_event, send_teams_welcome
from products.conversations.backend.teams import is_bot_added_event

logger = structlog.get_logger(__name__)

TEAMS_MESSAGE_TYPES = {"message"}


def _team_for_teams_tenant(tenant_id: str) -> Team | None:
    config = (
        TeamConversationsTeamsConfig.objects.filter(teams_tenant_id=tenant_id, teams_graph_access_token__isnull=False)
        .select_related("team")
        .first()
    )
    return config.team if config else None


def _claims_match_activity(claims: dict, activity: dict) -> bool:
    """
    Cross-check verified JWT claims against the plaintext activity body.

    The Bot Framework JWT authenticates the caller, but tenant attribution and
    the outbound bot-token target URL both come from JSON fields in the
    activity body (``channelData.tenant.id`` and ``serviceUrl``). Without
    tying them back to signature-verified claims, anyone in possession of a
    legitimate Bot Framework token (e.g. replay) could craft an activity that
    attributes messages to a different PostHog-connected tenant, or steer the
    bot's bearer token to a non-Microsoft URL.

    Per Microsoft's Bot Framework authentication spec, whenever a claim is
    present it MUST equal the activity field. Missing claims are tolerated
    (the allowlist check on ``serviceUrl`` still applies).
    """
    body_tenant_id = ((activity.get("channelData") or {}).get("tenant") or {}).get("id", "")
    claim_tenant_id = claims.get("tid") or ""
    if claim_tenant_id and body_tenant_id and claim_tenant_id != body_tenant_id:
        logger.warning(
            "supporthog_teams_tid_mismatch",
            body_tenant_id=body_tenant_id,
            claim_tenant_id=claim_tenant_id,
        )
        return False

    body_service_url = (activity.get("serviceUrl") or "").rstrip("/")
    if body_service_url and not is_trusted_teams_service_url(body_service_url):
        logger.warning("supporthog_teams_untrusted_service_url", service_url=body_service_url)
        return False

    claim_service_url = (claims.get("serviceurl") or "").rstrip("/")
    if claim_service_url and body_service_url and claim_service_url != body_service_url:
        logger.warning(
            "supporthog_teams_serviceurl_mismatch",
            body_service_url=body_service_url,
            claim_service_url=claim_service_url,
        )
        return False

    return True


def _route_activity_to_relevant_region(request: HttpRequest, activity: dict, claims: dict) -> None:
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

    if not _claims_match_activity(claims, activity):
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

    # IP-based throttle in front of the JWT/JWKS path — the first thing we'd do
    # on a request with a bogus token is an expensive signing-key lookup, so we
    # cap total request volume before it reaches that code.
    throttle = TeamsEventWebhookThrottle()
    if not throttle.allow_request(DRFRequest(request), view=None):  # type: ignore[arg-type]
        return HttpResponse(status=429)

    try:
        claims = validate_teams_request(request)
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
        _route_activity_to_relevant_region(request, activity, claims)
        return HttpResponse(status=202)

    # Proactive welcome on install (Teams Store cert 11.4.4.3). The serviceUrl
    # cross-check still applies, but we don't need a PostHog-side team match —
    # the customer hasn't necessarily completed the OAuth flow yet, and the
    # welcome card uses only the global Bot Framework token.
    #
    # We also re-run _claims_match_activity here so that an attacker holding a
    # valid Bot Framework JWT can't pair it with a body that points serviceUrl
    # at a different Microsoft regional endpoint than the one the JWT was
    # issued for, even though the practical impact is limited (Bot Connector
    # only delivers to conversations the bot is actually installed in).
    if activity_type == "conversationUpdate" and is_bot_added_event(activity):
        if not _claims_match_activity(claims, activity):
            return HttpResponse(status=200)
        cast(Any, send_teams_welcome).delay(activity=activity)
        return HttpResponse(status=200)

    # Acknowledge other activity types (installationUpdate, etc.)
    return HttpResponse(status=200)
