import json
from typing import Optional

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours
CACHE_KEY_PREFIX = "activity_log:details_fields"
REALTIME_FIELD_DISCOVERY_THRESHOLD = 20000


def _get_cache_key(organization_id: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{organization_id}"


def get_cached_fields(organization_id: str) -> Optional[dict]:
    try:
        client = get_client()
        key = _get_cache_key(organization_id)
        json_data = client.get(key)

        if not json_data:
            return None

        return json.loads(json_data)
    except Exception as e:
        capture_exception(e)
        return None


def cache_fields(organization_id: str, fields_data: dict, record_count: int) -> None:
    try:
        client = get_client()
        key = _get_cache_key(organization_id)
        json_data = json.dumps(fields_data, default=str)

        if record_count > REALTIME_FIELD_DISCOVERY_THRESHOLD:
            # Non-expiring cache for large orgs
            client.set(key, json_data)
        else:
            # 12h TTL for smaller orgs
            client.setex(key, CACHE_TTL_SECONDS, json_data)
    except Exception as e:
        capture_exception(e)
