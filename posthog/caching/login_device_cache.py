import hashlib
from typing import Optional

from posthog.redis import get_client

TTL_SECONDS = 180 * 24 * 60 * 60  # 180 days


def _cache_key(user_id: int, fingerprint: str) -> str:
    # TODO switch to sha256 hash
    # fingerprint is user controllable. a hash collision might be possible with md5
    # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
    return f"login_device:{user_id}:{hashlib.md5(fingerprint.encode()).hexdigest()}"


def check_and_cache_login_device(
    user_id: int, location: str, device_signature: str, legacy_short_user_agent: Optional[str] = None
) -> bool:
    """Check if this is a new device and cache it"""

    cache_key = _cache_key(user_id, f"{location}:{device_signature}")
    redis_client = get_client()

    if redis_client.exists(cache_key):
        redis_client.expire(cache_key, TTL_SECONDS)
        return False

    # Devices last seen under the older version-bearing fingerprint are still known devices. Without
    # this, narrowing the fingerprint would alert every user once as their cached entry stopped matching.
    if legacy_short_user_agent is not None and redis_client.exists(
        _cache_key(user_id, f"{location}:{legacy_short_user_agent}")
    ):
        redis_client.setex(cache_key, TTL_SECONDS, "1")
        return False

    redis_client.setex(cache_key, TTL_SECONDS, "1")
    return True
