import hashlib

from posthog.redis import get_client

TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def check_and_cache_login_device(user_id: int, location: str, short_user_agent: str) -> bool:
    """Check if this is a new device and cache it for 30 days"""

    # Create a unique device identifier based on location + user agent
    device_fingerprint = f"{location}:{short_user_agent}"
    device_hash = hashlib.md5(device_fingerprint.encode()).hexdigest()
    cache_key = f"login_device:{user_id}:{device_hash}"

    # Check if this device has logged in before
    redis_client = get_client()
    device_exists = redis_client.exists(cache_key)

    if device_exists:
        redis_client.expire(cache_key, TTL_SECONDS)
        return False
    else:
        redis_client.setex(cache_key, TTL_SECONDS, "1")
        return True
