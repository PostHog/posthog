import hashlib
from posthog.redis import get_client


def check_and_cache_login_device(user_id: int, ip_address: str, short_user_agent: str) -> bool:
    """Check if the user has logged in with this device before and cache it for 30 days"""

    # Create a unique device identifier based on ip + user agent
    device_fingerprint = f"{ip_address}:{short_user_agent}"
    device_hash = hashlib.md5(device_fingerprint.encode()).hexdigest()
    cache_key = f"login_device:{user_id}:{device_hash}"

    # Check if this device has logged in before
    redis_client = get_client()
    device_exists = redis_client.exists(cache_key)

    TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

    if device_exists:
        redis_client.expire(cache_key, TTL_SECONDS)
        return False
    else:
        redis_client.setex(cache_key, TTL_SECONDS, "1")
        return True
