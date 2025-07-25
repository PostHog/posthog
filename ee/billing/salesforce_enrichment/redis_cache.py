"""
Redis caching utilities for Salesforce enrichment workflow.

Follows PostHog's AI session summary patterns for large dataset caching.
"""

import gzip
import json
import uuid
from typing import Any, Optional


from posthog.redis import get_async_client
from posthog.temporal.common.logger import get_internal_logger

# 6-hour TTL for enrichment workflow data (balance freshness vs performance)
SALESFORCE_ENRICHMENT_REDIS_TTL = 6 * 60 * 60  # 6 hours in seconds

logger = get_internal_logger()


def generate_workflow_id() -> str:
    """Generate a unique workflow ID for Redis key scoping."""
    return str(uuid.uuid4())


def generate_cache_key(workflow_id: str | None = None, data_type: str = "all_accounts") -> str:
    """Generate Redis key following PostHog's hierarchical naming pattern."""
    # Use global cache key to prevent cache explosion and improve performance
    return f"salesforce-enrichment:global:{data_type}"


def _compress_redis_data(input_data: str) -> bytes:
    """Compress data for Redis storage following PostHog patterns."""
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes | str) -> str:
    """Decompress data retrieved from Redis following PostHog patterns."""
    if isinstance(raw_redis_data, bytes):
        return gzip.decompress(raw_redis_data).decode("utf-8")
    if isinstance(raw_redis_data, str):
        return raw_redis_data
    raise ValueError(f"Invalid Redis data type: {type(raw_redis_data)}")


async def store_accounts_in_redis(
    workflow_id: str,
    accounts_data: list[dict[str, Any]],
    ttl: int = SALESFORCE_ENRICHMENT_REDIS_TTL,
) -> None:
    """
    Store all Salesforce accounts in Redis with compression using global cache.

    Args:
        workflow_id: Workflow identifier (used for logging only with global cache)
        accounts_data: List of account dictionaries from Salesforce
        ttl: Time-to-live in seconds (default: 6 hours)
    """
    redis_client = get_async_client()
    redis_key = generate_cache_key(workflow_id, "all_accounts")

    try:
        # Serialize and compress data following PostHog patterns
        logger.info(f"🔄 REDIS: Serializing {len(accounts_data)} accounts for storage")
        accounts_json = json.dumps(accounts_data, default=str)
        compressed_data = _compress_redis_data(accounts_json)

        # Store with TTL
        logger.info(f"💾 REDIS: Storing compressed data in key: {redis_key}")
        await redis_client.setex(redis_key, ttl, compressed_data)
        logger.info(f"✅ REDIS: Successfully stored data with TTL {ttl}s")

        # Log storage metrics
        uncompressed_size = len(accounts_json.encode("utf-8"))
        compressed_size = len(compressed_data)
        compression_ratio = compressed_size / uncompressed_size if uncompressed_size > 0 else 0

        logger.info(
            "Stored Salesforce accounts in Redis (GLOBAL CACHE)",
            workflow_id=workflow_id,
            account_count=len(accounts_data),
            uncompressed_size_mb=round(uncompressed_size / 1024 / 1024, 2),
            compressed_size_mb=round(compressed_size / 1024 / 1024, 2),
            compression_ratio=round(compression_ratio, 3),
            ttl_hours=ttl / 3600,
            global_cache_key=redis_key,
        )

    except Exception as e:
        logger.exception(
            "Failed to store accounts in Redis",
            workflow_id=workflow_id,
            account_count=len(accounts_data),
            error=str(e),
        )
        raise


async def get_accounts_from_redis(
    workflow_id: str,
    offset: int = 0,
    limit: int = 1000,
) -> Optional[list[dict[str, Any]]]:
    """
    Retrieve accounts chunk from Redis cache using global cache.

    Args:
        workflow_id: Workflow identifier (used for logging only with global cache)
        offset: Starting index for pagination
        limit: Number of accounts to retrieve

    Returns:
        List of account dictionaries, or None if cache miss
    """
    redis_client = get_async_client()
    redis_key = generate_cache_key(workflow_id, "all_accounts")

    try:
        # Try to get from Redis
        logger.info(f"🔍 REDIS: Checking cache for key: {redis_key}")
        raw_redis_data = await redis_client.get(redis_key)
        if not raw_redis_data:
            logger.info(
                "❌ REDIS GLOBAL CACHE MISS: No data found for Salesforce accounts",
                workflow_id=workflow_id,
                offset=offset,
                limit=limit,
                redis_key=redis_key,
            )
            return None

        # Decompress and deserialize
        accounts_json = _decompress_redis_data(raw_redis_data)
        all_accounts = json.loads(accounts_json)

        # Paginate in memory (same logic as current implementation)
        start_idx = offset
        end_idx = min(offset + limit, len(all_accounts))

        if start_idx >= len(all_accounts):
            logger.info(
                "Redis cache: offset beyond available accounts",
                workflow_id=workflow_id,
                offset=offset,
                total_accounts=len(all_accounts),
            )
            return []

        chunk_accounts = all_accounts[start_idx:end_idx]

        logger.info(
            "Retrieved accounts from Redis GLOBAL cache",
            workflow_id=workflow_id,
            offset=offset,
            limit=limit,
            chunk_size=len(chunk_accounts),
            total_accounts=len(all_accounts),
        )

        return chunk_accounts

    except Exception as e:
        logger.exception(
            "Failed to retrieve accounts from Redis",
            workflow_id=workflow_id,
            offset=offset,
            limit=limit,
            error=str(e),
        )
        return None


async def cleanup_workflow_cache(workflow_id: str) -> None:
    """
    Clean up Redis global cache (NOTE: This affects ALL workflows using global cache).

    Following PostHog patterns: log but don't fail on cleanup errors,
    as TTL will handle expiration automatically.
    WARNING: Only use this for explicit cache invalidation, not routine cleanup.
    """
    redis_client = get_async_client()
    redis_key = generate_cache_key(workflow_id, "all_accounts")

    try:
        result = await redis_client.delete(redis_key)
        if result:
            logger.info("Cleaned up workflow cache", workflow_id=workflow_id)
        else:
            logger.info("No cache found to clean up", workflow_id=workflow_id)
    except Exception as e:
        # Log but don't fail - TTL will clean up automatically
        logger.exception(
            "Failed to clean up workflow cache (TTL will handle expiration)",
            workflow_id=workflow_id,
            error=str(e),
        )


async def check_cache_status(workflow_id: str) -> dict[str, Any]:
    """
    Check the status of cached data for debugging/monitoring.

    Returns:
        Dictionary with cache status information
    """
    redis_client = get_async_client()
    redis_key = generate_cache_key(workflow_id, "all_accounts")

    try:
        # Check if key exists
        exists = await redis_client.exists(redis_key)
        if not exists:
            return {"status": "not_found", "workflow_id": workflow_id}

        # Get TTL
        ttl = await redis_client.ttl(redis_key)

        # Get data size (without decompressing for efficiency)
        raw_data = await redis_client.get(redis_key)
        compressed_size = len(raw_data) if raw_data else 0

        return {
            "status": "found",
            "workflow_id": workflow_id,
            "ttl_seconds": ttl,
            "ttl_hours": round(ttl / 3600, 2) if ttl > 0 else 0,
            "compressed_size_mb": round(compressed_size / 1024 / 1024, 2),
        }

    except Exception as e:
        return {
            "status": "error",
            "workflow_id": workflow_id,
            "error": str(e),
        }
