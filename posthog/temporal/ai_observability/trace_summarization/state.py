"""Redis intermediate storage for passing text_repr between activities.

Stores gzip-compressed text representations in Redis so that only small
references (~100 bytes) flow through Temporal workflow history while the
large payloads (up to 2 MB) go through Redis.
"""

import gzip

import structlog
from redis import asyncio as aioredis

logger = structlog.get_logger(__name__)

REDIS_KEY_PREFIX = "llma:summarization"
REDIS_TTL_SECONDS = 12_000  # ~200 min, exceeds 180-min workflow timeout


def generate_redis_key(item_type: str, team_id: int, item_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}:{item_type}:{team_id}:{item_id}:text_repr"


async def store_text_repr(
    redis_client: aioredis.Redis,
    key: str,
    text_repr: str,
    ttl: int = REDIS_TTL_SECONDS,
) -> int:
    compressed = gzip.compress(text_repr.encode("utf-8"))
    await redis_client.setex(key, ttl, compressed)
    return len(compressed)


async def load_text_repr(redis_client: aioredis.Redis, key: str) -> str | None:
    raw = await redis_client.get(key)
    if raw is None:
        return None
    return gzip.decompress(raw).decode("utf-8")


async def delete_text_repr(redis_client: aioredis.Redis, key: str) -> None:
    try:
        await redis_client.delete(key)
    except Exception:
        logger.warning("Failed to delete Redis key, TTL will handle cleanup", key=key, exc_info=True)
