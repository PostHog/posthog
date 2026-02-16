import gzip
import json
from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client

from .constants import REDIS_TTL_SECONDS, SALESFORCE_ACCOUNTS_CACHE_KEY, SALESFORCE_ORG_MAPPINGS_CACHE_KEY


def _compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes) -> str:
    return gzip.decompress(raw_redis_data).decode("utf-8")


async def _get_cached_list(cache_key: str) -> list[dict[str, Any]] | None:
    """Retrieve and decompress a cached list from Redis.

    Returns:
        Parsed list, or None if cache miss/error
    """
    try:
        redis_client = get_async_client()
        raw_redis_data = await redis_client.get(cache_key)

        if not raw_redis_data:
            return None

        data_json = _decompress_redis_data(raw_redis_data)
        return json.loads(data_json)

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


async def store_org_mappings_in_redis(
    mappings_data: list[dict[str, Any]],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    """Store Salesforce org mappings in Redis with gzip compression."""
    redis_client = get_async_client()

    mappings_json = json.dumps(mappings_data, default=str)
    compressed_data = _compress_redis_data(mappings_json)

    await redis_client.setex(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, ttl, compressed_data)


async def get_org_mappings_from_redis() -> list[dict[str, Any]] | None:
    """Retrieve all org mappings from Redis cache.

    Returns:
        List of mapping dictionaries, or None if cache miss/error
    """
    return await _get_cached_list(SALESFORCE_ORG_MAPPINGS_CACHE_KEY)


async def get_cached_org_mappings_count() -> int | None:
    """Get the total count of cached org mappings.

    Returns:
        Total number of cached mappings, or None if cache miss/error
    """
    all_mappings = await _get_cached_list(SALESFORCE_ORG_MAPPINGS_CACHE_KEY)
    return len(all_mappings) if all_mappings is not None else None
