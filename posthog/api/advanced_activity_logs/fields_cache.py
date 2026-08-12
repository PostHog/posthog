import json
from typing import Optional

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

from .constants import CACHE_KEY_PREFIX, CACHE_TTL_SECONDS, SMALL_ORG_THRESHOLD


def _get_cache_key(organization_id: str, team_id: Optional[int] = None) -> str:
    """Discovery results are cached at the scope they were computed for.

    A project-scoped entry may only contain that project's metadata, so it cannot share a key with
    the organization-wide entry the background task builds.
    """
    if team_id is None:
        return f"{CACHE_KEY_PREFIX}:{organization_id}"
    return f"{CACHE_KEY_PREFIX}:{organization_id}:team:{team_id}"


def get_cached_fields(organization_id: str, team_id: Optional[int] = None) -> Optional[dict]:
    try:
        client = get_client()
        key = _get_cache_key(organization_id, team_id)
        json_data = client.get(key)

        if not json_data:
            return None

        return json.loads(json_data)
    except Exception as e:
        capture_exception(e)
        return None


def cache_fields(organization_id: str, fields_data: dict, record_count: int, team_id: Optional[int] = None) -> None:
    try:
        client = get_client()
        key = _get_cache_key(organization_id, team_id)
        json_data = json.dumps(fields_data, default=str)

        if record_count > SMALL_ORG_THRESHOLD:
            # Non-expiring cache for large orgs
            client.set(key, json_data)
        else:
            # 12h TTL for smaller orgs
            client.setex(key, CACHE_TTL_SECONDS, json_data)
    except Exception as e:
        capture_exception(e)


def delete_cached_fields(organization_id: str, team_id: Optional[int] = None) -> bool:
    """Delete cached fields for an organization, or for one project within it"""
    try:
        client = get_client()
        key = _get_cache_key(organization_id, team_id)
        return bool(client.delete(key))
    except Exception as e:
        capture_exception(e)
        return False
