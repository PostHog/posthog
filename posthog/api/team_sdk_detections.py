import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.http import JsonResponse

import structlog
import posthoganalytics
from rest_framework import exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.exceptions_capture import capture_exception
from posthog.models import Filter, Team
from posthog.models.event.query_event_list import query_events_list
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# 24 hour cache TTL for team SDK detections
TEAM_SDK_CACHE_EXPIRY = 60 * 60 * 24  # 24 hours

# SDK type mapping from $lib property to SdkType
SDK_TYPE_MAPPING = {
    "web": "web",
    "posthog-ios": "ios",
    "posthog-android": "android",
    "posthog-node": "node",
    "posthog-python": "python",
    "posthog-php": "php",
    "posthog-ruby": "ruby",
    "posthog-go": "go",
    "posthog-flutter": "flutter",
    "posthog-react-native": "react-native",
    "posthog-dotnet": "dotnet",
    "posthog-elixir": "elixir",
}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_sdk_detections(request: Request) -> JsonResponse:
    """
    Detect SDKs in use by the current user's team from recent events.
    Returns minimal detection data (NOT version metadata).
    Protected by sdk-doctor-beta feature flag.
    """
    # Check if user has access to SDK Doctor beta
    if not posthoganalytics.feature_enabled("sdk-doctor-beta", str(request.user.distinct_id)):
        raise exceptions.ValidationError("SDK Doctor is not enabled for this user")

    # Use the user's current team
    team_id = request.user.team.id

    # Check if force refresh is requested
    force_refresh = request.GET.get("force_refresh", "").lower() == "true"

    redis_client = get_client()
    cache_key = f"sdk_detections:team:{team_id}"

    # Skip cache if force_refresh is requested
    if not force_refresh:
        # Try cache first
        cached_data = redis_client.get(cache_key)
        if cached_data:
            try:
                data = json.loads(cached_data.decode("utf-8") if isinstance(cached_data, bytes) else cached_data)
                data["cached"] = True
                logger.info(f"[SDK Doctor] Team {team_id} SDK detections successfully read from cache")
                return JsonResponse(data)
            except (json.JSONDecodeError, AttributeError) as e:
                # Cache corrupted, continue to fetch fresh
                logger.warning(f"[SDK Doctor] Cache corrupted for team {team_id}", error=str(e))
                capture_exception(e)
    else:
        logger.info(f"[SDK Doctor] Force refresh requested for team {team_id}, bypassing cache")

    # Fetch fresh data from ClickHouse
    logger.info(f"[SDK Doctor] Team {team_id} SDK detections not found in cache, querying ClickHouse")
    try:
        detections = detect_team_sdks_from_events(team_id)
        if detections is not None:
            response_data = {
                "teamId": team_id,
                "detections": detections,
                "cached": False,
                "queriedAt": datetime.now(UTC).isoformat(),
            }

            # Cache the result
            redis_client.setex(cache_key, TEAM_SDK_CACHE_EXPIRY, json.dumps(response_data))
            logger.info(f"[SDK Doctor] Team {team_id} SDK detections cached successfully")
            return JsonResponse(response_data)
        else:
            logger.error(f"[SDK Doctor] No data received from ClickHouse for team {team_id}")
            return JsonResponse({"error": "Failed to detect SDKs. Please try again later."}, status=500)
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to detect SDKs for team {team_id}")
        capture_exception(e)
        # Return generic error in response, log actual error above
        return JsonResponse({"error": "Failed to detect SDKs. Please try again later."}, status=500)


def detect_team_sdks_from_events(team_id: int) -> Optional[list[dict[str, Any]]]:
    """
    Query ClickHouse for recent events and extract SDK usage.
    Returns list of SDK detections with minimal data.
    """
    try:
        # Get the team object
        team = Team.objects.get(id=team_id)

        # Create a filter for the last 7 days of events
        # Using 7 days as per the original requirement mentioned
        now = datetime.now(UTC)
        date_from = (now - timedelta(days=7)).isoformat()
        date_to = now.isoformat()

        # Create filter with date range and property filters
        filter_data = {
            "date_from": date_from,
            "date_to": date_to,
            "properties": [
                {"key": "$lib", "operator": "is_set", "value": "is_set", "type": "event"},
                {"key": "$lib_version", "operator": "is_set", "value": "is_set", "type": "event"},
            ],
        }

        filter = Filter(data=filter_data, team=team)

        # Query events with proper abstraction
        # Get more events to ensure we can group and count them properly
        events = query_events_list(
            filter=filter,
            team=team,
            request_get_query_dict={},
            order_by=["-timestamp"],
            action_id=None,
            limit=10000,  # Get enough events to properly aggregate SDKs
            offset=0,
        )

        if not events:
            return []

        # Group events by SDK type and version
        sdk_groups = {}
        total_events_processed = 0
        events_with_lib = 0
        events_filtered = 0
        events_included = 0

        for event in events:
            total_events_processed += 1
            properties = event.get("properties", {})
            # Properties might be a JSON string, parse it if needed
            if isinstance(properties, str):
                try:
                    properties = json.loads(properties)
                except (json.JSONDecodeError, TypeError):
                    properties = {}

            lib = properties.get("$lib")
            lib_version = properties.get("$lib_version")

            # Skip if missing required properties
            if not lib or not lib_version:
                continue

            events_with_lib += 1

            # Apply filtering
            if lib == "posthog-js-lite":
                logger.debug(f"[SDK Doctor] Filtering posthog-js-lite event")
                events_filtered += 1
                continue

            # Pass both properties and top-level distinct_id for filtering
            event_distinct_id = event.get("distinct_id", "")
            if not should_include_event(properties, event_distinct_id):
                events_filtered += 1
                logger.debug(f"[SDK Doctor] Event filtered: lib={lib}, version={lib_version}")
                continue

            events_included += 1

            # Map lib to SDK type
            sdk_type = map_lib_to_sdk_type(lib)
            if sdk_type == "other":
                logger.debug(f"[SDK Doctor] Skipping unknown SDK type: lib={lib}")
                continue  # Skip unknown SDK types

            # Create unique key for grouping
            group_key = f"{sdk_type}:{lib_version}"

            if group_key not in sdk_groups:
                sdk_groups[group_key] = {
                    "type": sdk_type,
                    "version": lib_version,
                    "count": 0,
                    "lastSeen": event.get("timestamp"),
                }

            sdk_groups[group_key]["count"] += 1
            # Update last seen if this event is more recent
            if event.get("timestamp") > sdk_groups[group_key]["lastSeen"]:
                sdk_groups[group_key]["lastSeen"] = event.get("timestamp")

        # Convert to list and sort by last seen
        detections = list(sdk_groups.values())
        detections.sort(key=lambda x: x["lastSeen"], reverse=True)

        # Limit to 50 SDK detections as per original logic
        detections = detections[:50]

        # Format timestamps
        for detection in detections:
            last_seen = detection["lastSeen"]
            if isinstance(last_seen, str):
                detection["lastSeen"] = last_seen
            elif hasattr(last_seen, "isoformat"):
                detection["lastSeen"] = last_seen.isoformat()
            else:
                detection["lastSeen"] = str(last_seen)

        # Log filtering statistics
        logger.info(
            f"[SDK Doctor] Event processing summary for team {team_id}: "
            f"total_processed={total_events_processed}, "
            f"with_lib={events_with_lib}, "
            f"filtered={events_filtered}, "
            f"included={events_included}, "
            f"unique_detections={len(detections)}"
        )

        return detections
    except Team.DoesNotExist:
        logger.exception(f"[SDK Doctor] Team {team_id} not found")
        return None
    except Exception as e:
        logger.exception(f"[SDK Doctor] Error querying events for team {team_id}")
        capture_exception(e)
        return None


def should_include_event(properties: dict[str, Any], distinct_id: str = "") -> bool:
    """
    Apply event filtering logic matching frontend behavior.
    Filters out:
    - Internal PostHog UI events (URLs containing /project/1)
    - Test events in debug mode (email or distinct_id = test@posthog.com)
    - posthog-js-lite events

    Args:
        properties: Event properties dict
        distinct_id: Top-level distinct_id from event (matches frontend event.distinct_id)
    """
    # In debug mode, filter out events from localhost PostHog UI
    from django.conf import settings

    is_debug = settings.DEBUG
    if is_debug:
        current_url = properties.get("$current_url", "")

        # Filter events WHERE THE EVENT ITSELF is from localhost (PostHog UI)
        # Keep events from file:// URLs (test files) even if they use localhost API
        if current_url and (
            current_url.startswith("http://localhost:8010")
            or current_url.startswith("http://localhost:8000")
            or current_url.startswith("http://127.0.0.1")
        ):
            return False

        # Also filter by email/distinct_id as backup
        email = properties.get("email", "")
        props_distinct_id = properties.get("distinct_id", "")
        if email == "test@posthog.com" or distinct_id == "test@posthog.com" or props_distinct_id == "test@posthog.com":
            return False

    return True


def map_lib_to_sdk_type(lib: str) -> str:
    """
    Map $lib property to SdkType.
    Returns 'other' for unknown SDKs.
    """
    return SDK_TYPE_MAPPING.get(lib, "other")
