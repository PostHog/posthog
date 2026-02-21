"""
Property value caching for property filter suggestions.

This module provides Redis caching for property value suggestions to improve
performance when users have large numbers of events.
"""

import json
import hashlib
from typing import Any, Optional

from posthog.redis import get_client

# 7 days in seconds
PROPERTY_VALUES_CACHE_TTL = 7 * 24 * 60 * 60

# How long to wait before allowing another background refresh (seconds)
PROPERTY_VALUES_REFRESH_COOLDOWN = 60

# Safety-net TTL for the task-running key; cleared explicitly on task completion
PROPERTY_VALUES_TASK_RUNNING_TTL = 5 * 60


def _make_cache_key(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> str:
    """
    Generate a Redis cache key for property values.

    Args:
        team_id: The team ID
        property_type: Type of property (event, person, session, flag)
        property_key: The property name/key
        search_value: Optional search filter value
        event_names: Optional list of event names to filter by (for event properties)

    Returns:
        Redis cache key string
    """
    # Create a stable key by including all relevant parameters
    key_parts = [
        f"team:{team_id}",
        f"type:{property_type}",
        f"key:{property_key}",
    ]

    if search_value:
        key_parts.append(f"search:{search_value}")

    if event_names:
        # Sort to ensure consistent key regardless of order
        sorted_events = sorted(event_names)
        key_parts.append(f"events:{','.join(sorted_events)}")

    # Use hash to keep key length reasonable
    key_string = "|".join(key_parts)
    key_hash = hashlib.sha256(key_string.encode()).hexdigest()[:16]

    return f"property_values:{key_hash}"


def get_cached_property_values(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> Optional[list[dict[str, Any]]]:
    """
    Retrieve cached property values from Redis.

    Args:
        team_id: The team ID
        property_type: Type of property (event, person, session, flag)
        property_key: The property name/key
        search_value: Optional search filter value
        event_names: Optional list of event names to filter by

    Returns:
        List of property value dicts if cached, None if not found
    """
    redis_client = get_client()
    cache_key = _make_cache_key(team_id, property_type, property_key, search_value, event_names)

    cached = redis_client.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            # If cache is corrupted, return None to trigger fresh query
            return None

    return None


def is_refresh_on_cooldown(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> bool:
    """Return True if a refresh was triggered within the cooldown window."""
    redis_client = get_client()
    cooldown_key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":refreshing"
    return redis_client.exists(cooldown_key) > 0


def set_refresh_cooldown(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> None:
    """Mark that a refresh was triggered; prevents re-triggering during the cooldown window."""
    redis_client = get_client()
    cooldown_key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":refreshing"
    redis_client.set(cooldown_key, "1", ex=PROPERTY_VALUES_REFRESH_COOLDOWN)


def set_task_running(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> None:
    """Mark that a background refresh task is in flight."""
    redis_client = get_client()
    key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":task_running"
    redis_client.set(key, "1", ex=PROPERTY_VALUES_TASK_RUNNING_TTL)


def is_task_running(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> bool:
    """Return True if a background refresh task is currently in flight."""
    redis_client = get_client()
    key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":task_running"
    return redis_client.exists(key) > 0


def clear_task_running(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> None:
    """Clear the task-running flag; called by the Celery task on completion."""
    redis_client = get_client()
    key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":task_running"
    redis_client.delete(key)


# Used for testing this PR only, should be removed
def clear_refresh_cooldown(
    team_id: int,
    property_type: str,
    property_key: str,
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> bool:
    """Delete the refresh cooldown key. Returns True if the key existed."""
    redis_client = get_client()
    cooldown_key = _make_cache_key(team_id, property_type, property_key, search_value, event_names) + ":refreshing"
    return redis_client.delete(cooldown_key) > 0


def cache_property_values(
    team_id: int,
    property_type: str,
    property_key: str,
    values: list[dict[str, Any]],
    search_value: Optional[str] = None,
    event_names: Optional[list[str]] = None,
) -> None:
    """
    Store property values in Redis cache with 7-day expiry.

    Args:
        team_id: The team ID
        property_type: Type of property (event, person, session, flag)
        property_key: The property name/key
        values: List of property value dicts to cache
        search_value: Optional search filter value
        event_names: Optional list of event names to filter by
    """
    redis_client = get_client()
    cache_key = _make_cache_key(team_id, property_type, property_key, search_value, event_names)

    # Serialize values to JSON
    cached_data = json.dumps(values)

    # Store with 7-day TTL
    redis_client.set(cache_key, cached_data, ex=PROPERTY_VALUES_CACHE_TTL)
