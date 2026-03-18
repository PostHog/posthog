import json
from typing import Any, cast

from django.conf import settings

import structlog
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from products.growth.dags.github_sdk_versions import SDK_TYPES
from products.growth.dags.team_sdk_versions import get_and_cache_team_sdk_versions

logger = structlog.get_logger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sdk_doctor(request: Request) -> Response:
    """
    Serve team SDK versions. Data is cached by Dagster job.
    Supports force_refresh=true for on-demand detection.
    """
    user = cast(User, request.user)

    team_id = cast(Team, user.team).id
    raw_force_refresh = request.GET.get("force_refresh", "")
    force_refresh = raw_force_refresh.lower() == "true"

    team_data = get_team_data(team_id, force_refresh)
    if not team_data:
        if settings.DEBUG:  # Running locally, usually doesn't have anything in the cache, just return empty
            logger.info(
                f"[SDK Doctor] Running locally, no data received from ClickHouse for team {team_id}, returning empty response"
            )
            return Response({}, status=200)

        return Response({"error": "Failed to get SDK versions. Please try again later."}, status=500)

    sdk_data = get_github_sdk_data()
    if not sdk_data:
        return Response({"error": "Failed to get GitHub SDK data. Please try again later."}, status=500)

    # Combine the team data with SDK data by including the date for each release
    # on the team data alongside whether it's the latest or not
    combined_data = {}
    for lib, entries in team_data.items():
        sdk_data_for_lib = sdk_data[lib]
        combined_data[lib] = {
            "latest_version": sdk_data_for_lib["latestVersion"],
            "usage": [
                {
                    **entry,
                    "is_latest": entry["lib_version"] == sdk_data_for_lib["latestVersion"],
                    "release_date": sdk_data_for_lib["releaseDates"].get(entry["lib_version"], None),
                }
                for entry in entries
            ],
        }

    return Response(combined_data, status=200)


def get_team_data(team_id: int, force_refresh: bool) -> dict[str, Any] | None:
    redis_client = get_client()
    cache_key = f"sdk_versions:team:{team_id}"

    if not force_refresh:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                sdk_versions = json.loads(
                    cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data
                )
                logger.info(f"[SDK Doctor] Team {team_id} SDK versions successfully read from cache")
                return sdk_versions
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[SDK Doctor] Cache corrupted for team {team_id}", error=str(e))
                capture_exception(e)
    else:
        logger.info(f"[SDK Doctor] Force refresh requested for team {team_id}, bypassing cache")

    logger.info(f"[SDK Doctor] Team {team_id} SDK versions not found in cache, querying ClickHouse")
    try:
        sdk_versions = get_and_cache_team_sdk_versions(team_id, redis_client)
        if sdk_versions is not None:
            logger.info(f"[SDK Doctor] Team {team_id} SDK versions cached successfully")
            return sdk_versions
        else:
            logger.error(f"[SDK Doctor] No data received from ClickHouse for team {team_id}")
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to get SDK versions for team {team_id}")
        capture_exception(e)

    return None


def get_github_sdk_data() -> dict[str, Any]:
    redis_client = get_client()

    data: dict[str, Any] = {}
    for sdk_type in SDK_TYPES:
        cache_key = f"github:sdk_versions:{sdk_type}"
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                parsed = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
                data[sdk_type] = parsed
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[SDK Doctor] Cache corrupted for {sdk_type}", error=str(e))
                capture_exception(e, {"sdk_type": sdk_type, "cache_key": cache_key})
        else:
            logger.warning(f"[SDK Doctor] {sdk_type} SDK info not found in cache")

    return data
