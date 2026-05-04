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
import random
import datetime as dt
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
MAX_RETRIES = 5
BASE_RETRY_DELAY = 0.1  # 100ms
MAX_RETRY_DELAY = 2.0  # 2 seconds


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

    try:
        # Try to acquire lock atomically
        lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=LOCK_TTL)

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
        # Always release the lock
        try:
            redis_client.delete(lock_key)
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


def get_or_calculate_quantiles(
    durations_list: list[int], hour_bucket: Optional[str] = None, max_retries: int = MAX_RETRIES
) -> Optional[list[float]]:
    """
    Get quantiles from cache or calculate and cache them atomically.

    Uses retry logic with exponential backoff to handle race conditions where
    multiple workflows try to calculate quantiles simultaneously.

    Args:
        durations_list: List of duration values in milliseconds
        hour_bucket: Optional hour bucket, defaults to current hour
        max_retries: Maximum number of retries for handling race conditions

    Returns:
        List of 99 quantile values (p1 through p99), or None on failure
    """
    if hour_bucket is None:
        hour_bucket = _get_current_hour_bucket()

    # First, try to get from cache
    cached_quantiles = get_quantiles(hour_bucket)
    if cached_quantiles is not None:
        return cached_quantiles

    # Cache miss - need to calculate quantiles
    import statistics

    if len(durations_list) < 2:
        LOGGER.warning(
            "Insufficient data for quantile calculation", hour_bucket=hour_bucket, data_points=len(durations_list)
        )
        return None

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

        # All retries exhausted, return calculated quantiles without caching
        LOGGER.warning(
            "Failed to cache quantiles after all retries, returning uncached values",
            hour_bucket=hour_bucket,
            max_retries=max_retries,
        )
        return quantiles

    except (statistics.StatisticsError, TypeError, ValueError) as e:
        LOGGER.warning(
            "Failed to calculate quantiles", hour_bucket=hour_bucket, error=str(e), data_points=len(durations_list)
        )
        return None
