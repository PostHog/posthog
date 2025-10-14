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
from posthog.models.user import User
from posthog.redis import get_client

from dags.sdk_doctor.github_sdk_versions import SDK_TYPES

logger = structlog.get_logger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def github_sdk_versions(request: Request) -> JsonResponse:
    """
    Serve cached GitHub SDK version data for SDK Doctor.
    Data is cached by Dagster job that runs every 6 hours.
    Protected by sdk-doctor-beta feature flag.
    """
    user = cast(User, request.user)
    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

    redis_client = get_client()
    response = {}
    for sdk_type in SDK_TYPES:
        cache_key = f"github:sdk_versions:{sdk_type}"
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                data = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
                response[sdk_type] = data
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"[SDK Doctor] Cache corrupted for {sdk_type}", error=str(e))
                capture_exception(e, {"sdk_type": sdk_type, "cache_key": cache_key})
        else:
            logger.warning(f"[SDK Doctor] {sdk_type} SDK info not found in cache")
            response[sdk_type] = {"error": "SDK data not available. Please try again later."}

    return JsonResponse(response)
