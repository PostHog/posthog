import json
from typing import cast

from django.http import JsonResponse

import structlog
import posthoganalytics
from rest_framework import exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from dags.sdk_doctor.team_sdk_versions import get_and_cache_team_sdk_versions

logger = structlog.get_logger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_sdk_versions(request: Request) -> JsonResponse:
    """
    Serve team SDK versions. Data is cached by Dagster job (runs every 6 hours).
    Supports force_refresh=true for on-demand detection.
    Protected by sdk-doctor-beta feature flag.
    """
    user = cast(User, request.user)

    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

    team_id = cast(Team, user.team).id
    raw_force_refresh = request.GET.get("force_refresh", "")
    force_refresh = raw_force_refresh.lower() == "true"

    redis_client = get_client()
    cache_key = f"sdk_versions:team:{team_id}"

    logger.info(
        f"[SDK Doctor] Team {team_id} SDK versions requested",
        team_id=team_id,
        force_refresh=force_refresh,
        raw_force_refresh=raw_force_refresh,
        cache_key=cache_key,
    )

    if not force_refresh:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                sdk_versions = json.loads(
                    cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data
                )
                logger.info(f"[SDK Doctor] Team {team_id} SDK versions successfully read from cache")
                return JsonResponse({"sdk_versions": sdk_versions, "cached": True}, safe=False)
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[SDK Doctor] Cache corrupted for team {team_id}", error=str(e))
                capture_exception(e)
    else:
        logger.info(f"[SDK Doctor] Force refresh requested for team {team_id}, bypassing cache")

    logger.info(f"[SDK Doctor] Team {team_id} SDK versions not found in cache, querying ClickHouse")
    try:
        sdk_versions = get_and_cache_team_sdk_versions(team_id, redis_client)
        if sdk_versions is not None:
            return JsonResponse({"sdk_versions": sdk_versions, "cached": False}, safe=False)
        else:
            logger.error(f"[SDK Doctor] No data received from ClickHouse for team {team_id}")
            return JsonResponse({"error": "Failed to get SDK versions. Please try again later."}, status=500)
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to get SDK versions for team {team_id}")
        capture_exception(e)
        return JsonResponse({"error": "Failed to get SDK versions. Please try again later."}, status=500)
