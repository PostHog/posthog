"""Redis storage for fetch_segments payload to avoid exceeding Temporal's 2 MB limit."""

from redis import asyncio as aioredis

from posthog.temporal.common.redis_payload import load_compressed_json, store_compressed_json

REDIS_KEY_PREFIX = "video_segment_clustering:fetch_result"
REDIS_TTL_SECONDS = 3600  # 1 hour, exceeds workflow duration


def generate_redis_key(team_id: int, workflow_run_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}:{team_id}:{workflow_run_id}"


async def store_fetch_result(
    redis_client: aioredis.Redis,
    key: str,
    document_ids: list[str],
    distinct_ids: list[str],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    await store_compressed_json(
        redis_client,
        key,
        {"document_ids": document_ids, "distinct_ids": distinct_ids},
        ttl=ttl,
    )


async def load_fetch_result(
    redis_client: aioredis.Redis,
    key: str,
) -> tuple[list[str], list[str]]:
    """Load fetch result from Redis. Raises ValueError if key not found or expired."""
    data = await load_compressed_json(redis_client, key)
    if data is None:
        raise ValueError(f"Redis key {key} not found or expired")
    return data["document_ids"], data["distinct_ids"]
