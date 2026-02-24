"""Shared Redis payload utilities for Temporal workflows that pass large data via Redis.

Used by session summary and video segment clustering to avoid exceeding Temporal's 2 MB limit.
"""

import gzip
import json

from redis import asyncio as aioredis


def compress_str(s: str) -> bytes:
    """Compress a string for Redis storage."""
    return gzip.compress(s.encode("utf-8"))


def decompress_bytes(raw: bytes) -> str:
    """Decompress gzip-compressed bytes to string. For sync use (e.g. polling Redis)."""
    return gzip.decompress(raw).decode("utf-8")


async def store_compressed_str(
    redis_client: aioredis.Redis,
    key: str,
    data: str,
    ttl: int = 3600,
) -> None:
    """Compress and store a string in Redis with TTL."""
    await redis_client.setex(key, ttl, compress_str(data))


async def load_compressed_str(
    redis_client: aioredis.Redis,
    key: str,
) -> str | None:
    """Load and decompress a string from Redis. Returns None if key missing or expired."""
    raw = await redis_client.get(key)
    if raw is None:
        return None
    return decompress_bytes(raw)


async def store_compressed_json(
    redis_client: aioredis.Redis,
    key: str,
    data: dict | list,
    ttl: int = 3600,
) -> None:
    """Compress and store JSON-serializable data in Redis with TTL."""
    await store_compressed_str(redis_client, key, json.dumps(data), ttl)


async def load_compressed_json(
    redis_client: aioredis.Redis,
    key: str,
) -> dict | list | None:
    """Load and parse JSON from Redis. Returns None if key missing or expired."""
    s = await load_compressed_str(redis_client, key)
    if s is None:
        return None
    return json.loads(s)
