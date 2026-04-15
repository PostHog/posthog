import gzip
import json
import asyncio
import datetime as dt
from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client

from .constants import (
    REDIS_TTL_SECONDS,
    SALESFORCE_ACCOUNTS_CACHE_KEY,
    SALESFORCE_ORG_MAPPINGS_CACHE_KEY,
    SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY,
)


def _compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_and_parse_redis_data(raw_redis_data: bytes) -> list[dict[str, Any]]:
    parsed = json.loads(gzip.decompress(raw_redis_data).decode("utf-8"))
    if not isinstance(parsed, list):
        raise TypeError(f"Expected list from Redis cache, got {type(parsed).__name__}")
    return parsed


async def _get_cached_list(cache_key: str, timeout: float = 30.0) -> list[dict[str, Any]] | None:
    """Retrieve and decompress a cached list from Redis.

    Returns:
        Parsed list, or None if cache miss/error/timeout
    """
    try:
        redis_client = get_async_client()
        raw_redis_data = await asyncio.wait_for(redis_client.get(cache_key), timeout=timeout)

        if not raw_redis_data:
            return None

        return _decompress_and_parse_redis_data(raw_redis_data)

    except TimeoutError:
        capture_exception(TimeoutError(f"Redis operation timed out after {timeout}s for key {cache_key}"))
        return None
    except Exception as e:
        capture_exception(e)
        return None


async def store_accounts_in_redis(
    accounts_data: list[dict[str, Any]],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    """Store all Salesforce accounts in Redis with gzip compression."""
    redis_client = get_async_client()

    accounts_json = json.dumps(accounts_data, default=str)
    compressed_data = _compress_redis_data(accounts_json)

    await redis_client.setex(SALESFORCE_ACCOUNTS_CACHE_KEY, ttl, compressed_data)


async def get_accounts_from_redis(
    offset: int = 0,
    limit: int = 1000,
) -> list[dict[str, Any]] | None:
    """Retrieve accounts chunk from global Redis cache.

    Args:
        offset: Starting index for pagination
        limit: Number of accounts to retrieve

    Returns:
        List of account dictionaries, or None if cache miss/error
    """
    all_accounts = await _get_cached_list(SALESFORCE_ACCOUNTS_CACHE_KEY)
    if all_accounts is None:
        return None

    if offset >= len(all_accounts):
        return []

    return all_accounts[offset : offset + limit]


async def get_cached_accounts_count() -> int | None:
    """Get the total count of cached accounts.

    Returns:
        Total number of cached accounts, or None if cache miss/error
    """
    all_accounts = await _get_cached_list(SALESFORCE_ACCOUNTS_CACHE_KEY)
    return len(all_accounts) if all_accounts is not None else None


_ORG_MAPPINGS_PIPELINE_BATCH = 5000  # Entries per RPUSH call during list population


async def store_org_mappings_in_redis(
    mappings_data: list[dict[str, Any]],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    """Store Salesforce org mappings as a Redis List for efficient pagination.

    Each mapping is stored as a separate JSON entry so LRANGE can return
    arbitrary pages without decompressing the entire dataset.
    """
    redis_client = get_async_client()
    pipe = await redis_client.pipeline()
    pipe.delete(SALESFORCE_ORG_MAPPINGS_CACHE_KEY)

    for i in range(0, len(mappings_data), _ORG_MAPPINGS_PIPELINE_BATCH):
        batch = mappings_data[i : i + _ORG_MAPPINGS_PIPELINE_BATCH]
        pipe.rpush(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, *[json.dumps(m, default=str) for m in batch])

    pipe.expire(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, ttl)
    await pipe.execute()


async def _lrange_json_or_none(key: str, start: int, end: int) -> list[dict[str, Any]] | None:
    """Fetch a range from a Redis List, returning None on cache miss or error."""
    try:
        redis_client = get_async_client()
        raw_items = await redis_client.lrange(key, start, end)

        if not raw_items:
            return None

        return [json.loads(item) for item in raw_items]

    except Exception as e:
        capture_exception(e)
        return None


async def get_org_mappings_page_from_redis(
    offset: int = 0,
    limit: int = 10000,
) -> list[dict[str, Any]] | None:
    """Retrieve a page of org mappings via LRANGE — no decompression needed.

    Args:
        offset: Starting index for pagination
        limit: Number of mappings to retrieve

    Returns:
        List of mapping dictionaries, empty list if past end, or None if key missing
    """
    return await _lrange_json_or_none(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, offset, offset + limit - 1)


async def get_org_mappings_from_redis() -> list[dict[str, Any]] | None:
    """Retrieve all org mappings from Redis cache.

    Returns:
        List of mapping dictionaries, or None if cache miss/error
    """
    return await _lrange_json_or_none(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, 0, -1)


async def get_cached_org_mappings_count() -> int | None:
    """Get the total count of cached org mappings via LLEN (O(1)).

    Returns:
        Total number of cached mappings, or None if key missing
    """
    try:
        redis_client = get_async_client()
        count = await redis_client.llen(SALESFORCE_ORG_MAPPINGS_CACHE_KEY)
        return count if count > 0 else None
    except Exception as e:
        capture_exception(e)
        return None


async def get_stripe_enrichment_watermark() -> tuple[dt.datetime, str] | None:
    """Read the high-water mark from the last successful stripe-enrichment run.

    Returns the keyset position ``(last_changed_at, posthog_organization_id)``
    of the last successfully processed row
    """
    redis_client = get_async_client()
    raw = await redis_client.get(SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY)
    if raw is None:
        return None
    value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    parsed = json.loads(value)
    return (
        dt.datetime.fromisoformat(parsed["last_changed_at"]),
        str(parsed["posthog_organization_id"]),
    )


async def set_stripe_enrichment_watermark(last_changed_at: dt.datetime, posthog_organization_id: str) -> None:
    """Persist the keyset high-water mark for the next incremental run.

    The key is intentionally not TTL'd so a missed run never silently degrades
    into a full resync — if the watermark is gone, it's gone on purpose.
    """
    payload = json.dumps(
        {
            "last_changed_at": last_changed_at.isoformat(),
            "posthog_organization_id": posthog_organization_id,
        }
    )
    redis_client = get_async_client()
    await redis_client.set(SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY, payload)
