import gzip
import json

import structlog
from redis import asyncio as aioredis

logger = structlog.get_logger(__name__)

REDIS_KEY_PREFIX = "subscription:change_summary"

MIN_TTL_SECONDS = 3 * 24 * 3600  # 3 days
MAX_TTL_SECONDS = 90 * 24 * 3600  # 90 days

FREQUENCY_TO_SECONDS = {
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
    "monthly": 30 * 24 * 3600,
    "yearly": 365 * 24 * 3600,
}


def generate_state_key(subscription_id: int, insight_id: int) -> str:
    return f"{REDIS_KEY_PREFIX}:{subscription_id}:{insight_id}:state"


def compute_ttl_seconds(frequency: str, interval: int) -> int:
    base_seconds = FREQUENCY_TO_SECONDS.get(frequency, 24 * 3600)
    ttl = base_seconds * interval * 3
    return max(MIN_TTL_SECONDS, min(ttl, MAX_TTL_SECONDS))


async def store_insight_state(
    redis_client: aioredis.Redis,
    key: str,
    state_data: dict,
    ttl: int,
) -> int:
    raw = json.dumps(state_data, default=str).encode("utf-8")
    compressed = gzip.compress(raw)
    await redis_client.setex(key, ttl, compressed)
    return len(compressed)


async def load_insight_state(redis_client: aioredis.Redis, key: str) -> dict | None:
    raw = await redis_client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception:
        logger.warning("Corrupted Redis state, treating as missing", key=key, exc_info=True)
        return None
