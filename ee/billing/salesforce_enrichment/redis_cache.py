import gzip
import json
import asyncio
from typing import Any, Optional

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client
from posthog.temporal.common.logger import get_logger

from .constants import REDIS_TTL_SECONDS, SALESFORCE_ACCOUNTS_CACHE_KEY

LOGGER = get_logger(__name__)


def _compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes) -> str:
    return gzip.decompress(raw_redis_data).decode("utf-8")


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
) -> Optional[list[dict[str, Any]]]:
    """Retrieve accounts chunk from global Redis cache.

    Args:
        offset: Starting index for pagination
        limit: Number of accounts to retrieve

    Returns:
        List of account dictionaries, or None if cache miss/error
    """
    try:
        redis_client = get_async_client()
        raw_redis_data = await redis_client.get(SALESFORCE_ACCOUNTS_CACHE_KEY)

        if not raw_redis_data:
            return None

        accounts_json = _decompress_redis_data(raw_redis_data)
        all_accounts = json.loads(accounts_json)

        if offset >= len(all_accounts):
            return []

        return all_accounts[offset : offset + limit]

    except Exception as e:
        capture_exception(e)
        return None


async def get_cached_accounts_count() -> Optional[int]:
    """Get the total count of cached accounts without fetching the data.

    Returns:
        Total number of cached accounts, or None if cache miss/error
    """
    logger = LOGGER.bind()

    try:
        logger.info("Getting Redis client")
        redis_client = get_async_client()

        logger.info("Fetching Redis data")
        raw_redis_data = await asyncio.wait_for(redis_client.get(SALESFORCE_ACCOUNTS_CACHE_KEY), timeout=30.0)

        if not raw_redis_data:
            logger.info("No cached data found")
            return None

        accounts_json = _decompress_redis_data(raw_redis_data)
        all_accounts = json.loads(accounts_json)
        count = len(all_accounts)
        logger.info(f"Found {count} cached accounts")
        return count

    except TimeoutError:
        logger.exception("Redis operation timed out after 30 seconds")
        return None
    except Exception as e:
        logger.exception(f"Redis error: {str(e)}")
        capture_exception(e)
        return None
