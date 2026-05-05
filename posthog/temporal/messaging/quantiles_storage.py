"""
Redis-based quantiles storage service for consistent percentile thresholds across workflows.

This module provides atomic caching of duration quantiles to ensure all realtime cohort workflows
use the same percentile boundaries, preventing overlapping threshold ranges between tiers.

Race Condition Handling:
- Uses Redis SET NX (atomic set-if-not-exists) to prevent multiple workflows from calculating quantiles
- Implements retry logic with exponential backoff when cache write fails due to race conditions
- TTL set to 2 hours to ensure fresh data while allowing workflow coordination
"""

import json
import time
import uuid
import random
import datetime as dt
import statistics
from typing import Optional

import structlog

from posthog.redis import get_client

LOGGER = structlog.get_logger(__name__)

# Cache key format: quantiles:2024-01-15:14 (hourly buckets)
QUANTILES_KEY_PREFIX = "duration_quantiles:"
# Short TTL since we want relatively fresh data but need consistency within the hour
DEFAULT_TTL = 2 * 60 * 60  # 2 hours
# Lock to prevent race conditions when calculating quantiles
LOCK_KEY_PREFIX = "duration_quantiles_lock:"
LOCK_TTL = 300  # 5 minutes
# Retry configuration for handling race conditions
# Conservative limits to avoid blocking database_sync_to_async thread pool
MAX_RETRIES = 3
BASE_RETRY_DELAY = 0.05  # 50ms
MAX_RETRY_DELAY = 0.2  # 200ms max


def _get_cache_key(hour_bucket: str) -> str:
    """Generate Redis key for quantiles cache."""
    return f"{QUANTILES_KEY_PREFIX}{hour_bucket}"


def _get_lock_key(hour_bucket: str) -> str:
    """Generate Redis key for quantiles calculation lock."""
    return f"{LOCK_KEY_PREFIX}{hour_bucket}"


def _get_current_hour_bucket() -> str:
    """Get current hour bucket for cache key (e.g., '2024-01-15:14')."""
    now = dt.datetime.now(dt.UTC)
    return now.strftime("%Y-%m-%d:%H")


def _get_previous_hour_bucket() -> str:
    """Get previous hour bucket for fallback cache lookup (e.g., '2024-01-15:13')."""
    now = dt.datetime.now(dt.UTC)
    previous_hour = now - dt.timedelta(hours=1)
    return previous_hour.strftime("%Y-%m-%d:%H")


def store_quantiles(quantiles_data: list[float], hour_bucket: Optional[str] = None) -> bool:
    """
    Atomically store quantiles in Redis if not already cached.

    Args:
        quantiles_data: List of 99 quantile values (p1 through p99)
        hour_bucket: Optional hour bucket, defaults to current hour

    Returns:
        True if successfully stored, False if another process already stored them
    """
    if hour_bucket is None:
        hour_bucket = _get_current_hour_bucket()

    cache_key = _get_cache_key(hour_bucket)
    lock_key = _get_lock_key(hour_bucket)

    redis_client = get_client()
    lock_token = None

    try:
        # Generate unique token for this lock acquisition
        lock_token = uuid.uuid4().hex

        # Try to acquire lock atomically with unique token
        lock_acquired = redis_client.set(lock_key, lock_token, nx=True, ex=LOCK_TTL) or False

        if not lock_acquired:
            LOGGER.info(
                "Quantiles calculation lock already held by another process",
                hour_bucket=hour_bucket,
                cache_key=cache_key,
            )
            return False

        # Check if cache was set while we were acquiring the lock
        if redis_client.exists(cache_key):
            LOGGER.info(
                "Quantiles already cached by another process during lock acquisition",
                hour_bucket=hour_bucket,
                cache_key=cache_key,
            )
            return False

        # Store quantiles with TTL
        quantiles_json = json.dumps(quantiles_data)
        redis_client.setex(cache_key, DEFAULT_TTL, quantiles_json)

        LOGGER.info(
            "Successfully stored quantiles in cache",
            hour_bucket=hour_bucket,
            cache_key=cache_key,
            quantiles_count=len(quantiles_data),
            ttl_seconds=DEFAULT_TTL,
        )

        return True

    except Exception as e:
        LOGGER.warning("Failed to store quantiles in cache", hour_bucket=hour_bucket, cache_key=cache_key, error=str(e))
        return False

    finally:
        # Only release the lock if we acquired it and still hold the same token
        if lock_token:
            try:
                # Use Lua script for atomic compare-and-delete
                lua_script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("DEL", KEYS[1])
                else
                    return 0
                end
                """
                result = redis_client.eval(lua_script, 1, lock_key, lock_token)
                if result == 0:
                    LOGGER.warning(
                        "Lock token mismatch during release - lock may have expired or been taken by another process",
                        lock_key=lock_key,
                        hour_bucket=hour_bucket,
                    )
            except Exception as e:
                LOGGER.warning("Failed to release quantiles calculation lock", lock_key=lock_key, error=str(e))


def get_quantiles(hour_bucket: Optional[str] = None) -> Optional[list[float]]:
    """
    Retrieve cached quantiles from Redis.

    Args:
        hour_bucket: Optional hour bucket, defaults to current hour

    Returns:
        List of 99 quantile values if cached, None if not found
    """
    if hour_bucket is None:
        hour_bucket = _get_current_hour_bucket()

    cache_key = _get_cache_key(hour_bucket)
    redis_client = get_client()

    try:
        cached_data = redis_client.get(cache_key)

        if cached_data is None:
            LOGGER.info("No quantiles found in cache", hour_bucket=hour_bucket, cache_key=cache_key)
            return None

        quantiles_data = json.loads(cached_data)

        LOGGER.info(
            "Successfully retrieved quantiles from cache",
            hour_bucket=hour_bucket,
            cache_key=cache_key,
            quantiles_count=len(quantiles_data),
        )

        return quantiles_data

    except (json.JSONDecodeError, TypeError) as e:
        LOGGER.warning(
            "Failed to parse cached quantiles data", hour_bucket=hour_bucket, cache_key=cache_key, error=str(e)
        )
        # Delete corrupted cache entry
        try:
            redis_client.delete(cache_key)
        except Exception:
            pass
        return None

    except Exception as e:
        LOGGER.warning(
            "Failed to retrieve quantiles from cache", hour_bucket=hour_bucket, cache_key=cache_key, error=str(e)
        )
        return None


def get_cached_quantiles_or_calculate(
    durations_list: list[int], hour_bucket: Optional[str] = None, max_retries: int = MAX_RETRIES
) -> Optional[list[float]]:
    """
    Get quantiles from cache first, regardless of current data size.
    Only calculate new quantiles if cache is empty and we have sufficient data.

    This ensures workflows can reuse cached quantiles even when the current
    query returns insufficient data (e.g., cohort count dropped mid-hour).
    """
    if hour_bucket is None:
        hour_bucket = _get_current_hour_bucket()

    # First, try to get from current hour bucket cache
    cached_quantiles = get_quantiles(hour_bucket)
    if cached_quantiles is not None:
        return cached_quantiles

    # Cache miss - try previous hour bucket to handle hour-boundary issue
    # This prevents overlapping thresholds when schedules run near :59/:00
    previous_hour_bucket = _get_previous_hour_bucket()
    if previous_hour_bucket != hour_bucket:  # Only check if different from current
        cached_quantiles = get_quantiles(previous_hour_bucket)
        if cached_quantiles is not None:
            LOGGER.info(
                "Using quantiles from previous hour bucket to handle hour-boundary timing",
                current_bucket=hour_bucket,
                previous_bucket=previous_hour_bucket,
            )
            return cached_quantiles

    # No cache available - only calculate if we have sufficient current data
    if len(durations_list) < 2:
        LOGGER.error(
            "No cached quantiles available and insufficient current data for calculation",
            hour_bucket=hour_bucket,
            previous_bucket=previous_hour_bucket,
            data_points=len(durations_list),
        )
        return None

    # Continue with calculation using the current implementation
    return _calculate_and_cache_quantiles(durations_list, hour_bucket, max_retries)


def _calculate_and_cache_quantiles(
    durations_list: list[int], hour_bucket: str, max_retries: int = MAX_RETRIES
) -> Optional[list[float]]:
    """
    Calculate and cache quantiles atomically with retry logic for race conditions.

    Assumes cache has already been checked. This function only calculates new quantiles
    when we know we have sufficient data and need to populate the cache.

    Args:
        durations_list: List of duration values in milliseconds (must have >= 2 elements)
        hour_bucket: Time bucket for cache key
        max_retries: Maximum number of retries for handling race conditions

    Returns:
        List of 99 quantile values (p1 through p99), or None on failure
    """
    try:
        # Calculate quantiles
        quantiles = statistics.quantiles(durations_list, n=100, method="inclusive")

        # Try to store in cache with retry logic for race conditions
        for attempt in range(max_retries):
            stored = store_quantiles(quantiles, hour_bucket)

            if stored:
                # We successfully stored the quantiles
                LOGGER.info(
                    "Successfully calculated and cached quantiles",
                    hour_bucket=hour_bucket,
                    attempt=attempt + 1,
                    data_points=len(durations_list),
                )
                return quantiles

            # Another process stored quantiles while we were calculating
            # Try to retrieve the stored values
            cached_quantiles = get_quantiles(hour_bucket)
            if cached_quantiles is not None:
                LOGGER.info(
                    "Using quantiles calculated by another process", hour_bucket=hour_bucket, attempt=attempt + 1
                )
                return cached_quantiles

            # Cache still empty, retry with exponential backoff
            if attempt < max_retries - 1:
                delay = min(BASE_RETRY_DELAY * (2**attempt) + random.uniform(0, 0.1), MAX_RETRY_DELAY)
                LOGGER.info(
                    "Retrying quantiles calculation after delay",
                    hour_bucket=hour_bucket,
                    attempt=attempt + 1,
                    delay_seconds=delay,
                )
                time.sleep(delay)

        # All retries exhausted. Do not return uncached locally computed quantiles,
        # because doing so can reintroduce inconsistent percentile boundaries across workflows.
        # Perform one final cache read in case another process populated the cache
        # after our last retry attempt, otherwise fail closed.
        cached_quantiles = get_quantiles(hour_bucket)
        if cached_quantiles is not None:
            LOGGER.info(
                "Using quantiles calculated by another process after final cache check",
                hour_bucket=hour_bucket,
                max_retries=max_retries,
            )
            return cached_quantiles

        LOGGER.error(
            "Failed to obtain cached quantiles after all retries; returning None to preserve consistency",
            hour_bucket=hour_bucket,
            max_retries=max_retries,
        )
        return None

    except (statistics.StatisticsError, TypeError, ValueError) as e:
        LOGGER.warning(
            "Failed to calculate quantiles", hour_bucket=hour_bucket, error=str(e), data_points=len(durations_list)
        )
        return None
