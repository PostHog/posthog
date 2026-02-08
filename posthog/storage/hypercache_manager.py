"""
Batch management operations for HyperCache-backed team caches.

This module provides unified batch operations for managing team-indexed HyperCaches
(flags, team metadata, etc.). Each cache type can define a HyperCacheManagementConfig
that specifies how to perform batch operations.

Operations include:
- Invalidating all caches for a namespace
- Warming all caches with configurable batching and TTL staggering
- Gathering cache statistics and coverage metrics
"""

import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from django.db import connection

import structlog
from posthoganalytics import capture_exception
from prometheus_client import Counter, Gauge

from posthog.metrics import pushed_metrics_registry
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache

logger = structlog.get_logger(__name__)


# Configuration constants for cache operations
# These affect performance vs resource usage tradeoffs

# Pipeline batch size for Redis operations
# Balance between network round trips (smaller = more trips) and memory (larger = more memory)
# 5000 chosen to match team processing batch size and minimize network overhead
# With 200K teams, this means ~40 round trips
REDIS_PIPELINE_BATCH_SIZE = 5000

# Sample size for cache size analysis
# Smaller = faster but less accurate, larger = slower but more representative
# 1000 chosen for ~3% margin of error (vs ~10% with n=100) on 200K team population
# Adds ~2-3 seconds vs 100, but provides much better accuracy for operational analysis
CACHE_SIZE_SAMPLE_LIMIT = 1000


# Consolidated HyperCache metrics with namespace labels
# These replace cache-specific metrics in flags_cache.py and team_metadata_cache.py
# Note: Batch refresh duration is tracked by the generic posthog_celery_task_duration_seconds metric

HYPERCACHE_SIGNAL_UPDATE_COUNTER = Counter(
    "posthog_hypercache_signal_updates",
    "Cache updates triggered by Django signals",
    labelnames=["namespace", "operation", "result"],
)

HYPERCACHE_INVALIDATION_COUNTER = Counter(
    "posthog_hypercache_invalidations",
    "Full cache invalidations (schema changes)",
    labelnames=["namespace"],
)


def push_hypercache_stats_metrics(
    namespace: str,
    coverage_percent: float,
    entries_total: int,
    expiry_tracked_total: int,
    size_bytes: int | None,
) -> None:
    """
    Push HyperCache stats metrics to Pushgateway for single-value display.

    Gauge metrics are pushed to Pushgateway instead of using module-level gauges
    to ensure only one value per metric appears in Grafana dashboards.

    Args:
        namespace: The HyperCache namespace (e.g., "feature_flags", "team_metadata")
        coverage_percent: Percentage of teams with cached data
        entries_total: Total number of entries in the HyperCache
        expiry_tracked_total: Number of entries tracked in the expiry sorted set
        size_bytes: Estimated total cache size in bytes (None if unknown)
    """
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        return

    try:
        with pushed_metrics_registry(f"hypercache_stats_{namespace}") as registry:
            coverage_gauge = Gauge(
                "posthog_hypercache_coverage_percent",
                "Percentage of teams with cached data",
                labelnames=["namespace"],
                registry=registry,
            )
            coverage_gauge.labels(namespace=namespace).set(coverage_percent)

            entries_gauge = Gauge(
                "posthog_hypercache_entries_total",
                "Total number of entries in the HyperCache",
                labelnames=["namespace"],
                registry=registry,
            )
            entries_gauge.labels(namespace=namespace).set(entries_total)

            expiry_tracked_gauge = Gauge(
                "posthog_hypercache_expiry_tracked_total",
                "Number of entries tracked in the expiry sorted set",
                labelnames=["namespace"],
                registry=registry,
            )
            expiry_tracked_gauge.labels(namespace=namespace).set(expiry_tracked_total)

            if size_bytes is not None:
                size_gauge = Gauge(
                    "posthog_hypercache_size_bytes",
                    "Estimated total cache size in bytes",
                    labelnames=["namespace"],
                    registry=registry,
                )
                size_gauge.labels(namespace=namespace).set(size_bytes)
    except Exception as e:
        logger.warning("Failed to push hypercache stats to Pushgateway", error=str(e), namespace=namespace)


def push_hypercache_teams_processed_metrics(
    namespace: str,
    successful: int,
    failed: int,
) -> None:
    """
    Push teams processed metrics to Pushgateway after batch refresh operations.

    Uses Gauges instead of Counters because Counters don't work well with PushGateway
    (they reset on each push). Gauges show the count from the most recent batch run,
    which is the relevant information for an hourly task.

    Args:
        namespace: The HyperCache namespace (e.g., "feature_flags", "team_metadata")
        successful: Number of teams successfully processed
        failed: Number of teams that failed processing
    """
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        return

    try:
        with pushed_metrics_registry(f"hypercache_teams_processed_{namespace}") as registry:
            success_gauge = Gauge(
                "posthog_hypercache_teams_processed_last_run",
                "Teams processed in the last batch refresh run",
                labelnames=["namespace", "result"],
                registry=registry,
            )
            success_gauge.labels(namespace=namespace, result="success").set(successful)
            success_gauge.labels(namespace=namespace, result="failure").set(failed)
    except Exception as e:
        logger.warning("Failed to push hypercache teams processed to Pushgateway", error=str(e), namespace=namespace)


class UpdateFn(Protocol):
    """Protocol for cache update functions that accept team and optional TTL."""

    def __call__(self, team: Team | int, ttl: int | None = None) -> bool: ...


@dataclass
class HyperCacheManagementConfig:
    """
    Configuration for batch HyperCache management operations.

    Each HyperCache (flags, team metadata, etc.) should define one of these
    configs to specify how batch operations should work.

    Most properties are derived from conventions to reduce boilerplate.
    Only 3 properties need to be specified explicitly.

    Metrics are now consolidated and use namespace labels instead of per-cache counters.
    """

    # Required properties
    hypercache: HyperCache  # HyperCache instance
    update_fn: UpdateFn  # Function to update cache for a team
    cache_name: str  # Canonical cache name (e.g., "flags", "team_metadata")

    # Optional properties for verification optimization
    # If set, only teams in this set will have full DB data loaded during verification.
    # Teams not in this set will use a fast-path check against empty_cache_value.
    get_team_ids_needing_full_verification_fn: Callable[[], set[int]] | None = None
    # The expected cache value for teams that don't need full verification (e.g., {"flags": []})
    empty_cache_value: dict | None = None

    # Optional batch function to determine which teams should skip fixes.
    # Used to implement grace periods for recently updated data, avoiding race
    # conditions between async cache updates and verification.
    # Takes a list of team IDs, returns a set of team IDs that should skip fixes.
    # Called once per batch for efficiency (avoids N+1 queries).
    get_team_ids_to_skip_fix_fn: Callable[[list[int]], set[int]] | None = None

    def __post_init__(self) -> None:
        """Validate that optimization fields are set together."""
        has_team_ids_fn = self.get_team_ids_needing_full_verification_fn is not None
        has_empty_value = self.empty_cache_value is not None

        if has_team_ids_fn != has_empty_value:
            raise ValueError(
                "Verification optimization requires both get_team_ids_needing_full_verification_fn "
                "and empty_cache_value to be set together (either both set or both None)"
            )

    # Derived properties (computed from required properties using conventions)
    @property
    def namespace(self) -> str:
        """Cache namespace from HyperCache (e.g., "feature_flags", "team_metadata")."""
        return self.hypercache.namespace

    @property
    def cache_display_name(self) -> str:
        """Human-readable cache name for display (e.g., "flags", "team metadata")."""
        return self.cache_name.replace("_", " ")

    @property
    def _django_key_prefix(self) -> str:
        """Get Django cache key prefix (e.g., 'posthog:1:')."""
        # Django redis cache uses KEY_PREFIX + VERSION to build the full prefix
        # Default version is 1, resulting in "posthog:1:" prefix
        cache_client = self.hypercache.cache_client
        key_prefix = getattr(cache_client, "key_prefix", "")
        version = getattr(cache_client, "version", 1)
        if key_prefix:
            return f"{key_prefix}:{version}:"
        return ""

    @property
    def redis_pattern(self) -> str:
        """Redis key pattern for scanning all cache entries."""
        prefix = "team_tokens" if self.hypercache.token_based else "teams"
        django_prefix = self._django_key_prefix
        return f"{django_prefix}cache/{prefix}/*/{self.namespace}/*"

    @property
    def redis_stats_pattern(self) -> str:
        """Specific Redis pattern for stats (includes value file)."""
        prefix = "team_tokens" if self.hypercache.token_based else "teams"
        django_prefix = self._django_key_prefix
        return f"{django_prefix}cache/{prefix}/*/{self.namespace}/{self.hypercache.value}"

    @property
    def log_prefix(self) -> str:
        """Prefix for log messages (e.g., "flags caches", "team metadata caches")."""
        return f"{self.cache_display_name} caches"

    @property
    def management_command_name(self) -> str:
        """Name of management command for detailed analysis."""
        return f"analyze_{self.cache_name}_cache_sizes"


def invalidate_all_caches(config: HyperCacheManagementConfig) -> int:
    """
    Invalidate all caches for a specific HyperCache namespace.

    Scans Redis for all keys matching the cache pattern, deletes them,
    and clears the expiry tracking sorted set.

    Args:
        config: Cache configuration specifying which cache to invalidate

    Returns:
        Number of cache keys deleted
    """
    try:
        redis_client = get_client(config.hypercache.redis_url)

        deleted = 0
        for key in redis_client.scan_iter(match=config.redis_pattern, count=1000):
            redis_client.delete(key)
            deleted += 1

        # Clear the expiry tracking sorted set
        if config.hypercache.expiry_sorted_set_key:
            redis_client.delete(config.hypercache.expiry_sorted_set_key)

        HYPERCACHE_INVALIDATION_COUNTER.labels(namespace=config.namespace).inc()

        logger.info(f"Invalidated all {config.log_prefix}", deleted_keys=deleted)
        return deleted
    except Exception as e:
        logger.exception(f"Failed to invalidate {config.log_prefix}", error=str(e))
        capture_exception(e)
        return 0


def warm_caches(
    config: HyperCacheManagementConfig,
    batch_size: int = 1000,
    invalidate_first: bool = False,
    stagger_ttl: bool = True,
    min_ttl_days: int = 5,
    max_ttl_days: int = 7,
    team_ids: list[int] | None = None,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
    batch_start_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """
    Warm cache for teams (all or specific subset).

    Run as a management command for initial cache build or when schema changes require
    cache invalidation. Processes teams in batches with staggered TTLs to avoid
    synchronized expiration. Continues on errors.

    Uses persistent database connection to avoid connection overhead across batches.
    With CONN_MAX_AGE=0, each query creates a new connection (20-50ms overhead).
    By maintaining a single connection, we eliminate this overhead for batch operations.

    Args:
        config: Cache configuration specifying which cache to warm
        batch_size: Number of teams to process at a time
        invalidate_first: If True, clear all caches before warming (ignored when team_ids provided)
        stagger_ttl: If True, randomize TTLs between min/max to avoid synchronized expiration
        min_ttl_days: Minimum TTL in days (when staggering)
        max_ttl_days: Maximum TTL in days (when staggering)
        team_ids: Optional list of team IDs to warm (if None, warms all teams)
        progress_callback: Optional callback for progress reporting.
            Called with (processed, total, successful, failed) after each batch.
        batch_start_callback: Optional callback called before each batch starts.
            Called with (batch_number, batch_size) where batch_number is 1-indexed.

    Returns:
        Tuple of (successful_updates, failed_updates)
    """
    # Establish persistent database connection for batch operations
    # This avoids connection overhead (20-50ms per query) across all batches
    # Skip in tests to avoid interfering with test database management
    use_connection_pooling = not settings.TEST

    if use_connection_pooling:
        connection.ensure_connection()

    try:
        # Skip invalidation when warming specific teams (doesn't make sense for subset)
        if invalidate_first:
            if team_ids:
                logger.warning("Skipping invalidation when warming specific teams")
            else:
                logger.info(f"Invalidating all existing {config.log_prefix} before warming")
                invalidated = invalidate_all_caches(config)
                logger.info("Invalidated caches", count=invalidated)

        # Filter to specific teams if requested
        teams_queryset = Team.objects.select_related("organization", "project")
        if team_ids:
            teams_queryset = teams_queryset.filter(id__in=team_ids)

        total_teams = teams_queryset.count()

        logger.info(
            f"Starting {config.log_prefix} warm",
            total_teams=total_teams,
            batch_size=batch_size,
            stagger_ttl=stagger_ttl,
            invalidate_first=invalidate_first and not team_ids,
            specific_teams=team_ids is not None,
        )

        successful = 0
        failed = 0
        processed = 0
        batch_number = 0

        last_id = 0
        while True:
            batch = list(teams_queryset.filter(id__gt=last_id).order_by("id")[:batch_size])
            if not batch:
                break

            batch_number += 1

            # Notify caller that batch is starting
            if batch_start_callback:
                batch_start_callback(batch_number, len(batch))

            # Pre-load data for all teams in batch if the hypercache has batch loading
            batch_data = None
            if config.hypercache.batch_load_fn:
                try:
                    batch_data = config.hypercache.batch_load_fn(batch)
                except Exception as e:
                    logger.warning(
                        f"Batch load failed for {config.log_prefix}, falling back to individual loads",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            for team in batch:
                try:
                    # Calculate TTL for this team
                    if stagger_ttl:
                        ttl_seconds = random.randint(min_ttl_days * 24 * 3600, max_ttl_days * 24 * 3600)
                    else:
                        ttl_seconds = None

                    # Use pre-loaded data if available (set_cache_value tracks expiry automatically)
                    if batch_data and team.id in batch_data:
                        config.hypercache.set_cache_value(team, batch_data[team.id], ttl=ttl_seconds)
                    else:
                        # Fall back to regular update (will load individually)
                        config.update_fn(team, ttl=ttl_seconds)

                    successful += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to warm {config.log_prefix[:-1]} for team",
                        team_id=team.id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    capture_exception(e)
                    failed += 1

                processed += 1

            last_id = batch[-1].id

            # Report progress via callback after each batch
            if progress_callback:
                progress_callback(processed, total_teams, successful, failed)

            if processed % (batch_size * 10) == 0:
                logger.info(
                    f"{config.log_prefix.capitalize()} warm progress",
                    processed=processed,
                    total=total_teams,
                    successful=successful,
                    failed=failed,
                    percent=round(100 * processed / total_teams, 1),
                )

        logger.info(
            f"{config.log_prefix.capitalize()} warm completed",
            total_teams=total_teams,
            successful=successful,
            failed=failed,
        )

        return successful, failed
    finally:
        # Close the connection only if we opened it (not in tests)
        if use_connection_pooling:
            connection.close()


def get_cache_stats(config: HyperCacheManagementConfig) -> dict[str, Any]:
    """
    Get statistics about a HyperCache.

    Scans Redis to calculate coverage, TTL distribution, and memory estimates.
    Updates Prometheus gauges with the latest metrics.

    Uses Redis pipelining to batch operations and reduce network round trips
    by ~90% (e.g., 100K individual calls → 100 batched calls).

    Args:
        config: Cache configuration specifying which cache to analyze

    Returns:
        Dictionary with cache statistics including size information
    """
    try:
        redis_client = get_client(config.hypercache.redis_url)

        total_keys = 0
        ttl_buckets = {
            "expired": 0,
            "expires_1h": 0,
            "expires_24h": 0,
            "expires_7d": 0,
            "expires_later": 0,
        }

        sample_sizes: list[int] = []
        sample_limit = CACHE_SIZE_SAMPLE_LIMIT

        # Use pipelining to batch Redis operations and reduce network round trips
        pipeline_batch_size = REDIS_PIPELINE_BATCH_SIZE
        pipeline = redis_client.pipeline(transaction=False)
        batch_keys: list[bytes] = []

        for key in redis_client.scan_iter(match=config.redis_stats_pattern, count=1000):
            # Queue TTL command in pipeline
            pipeline.ttl(key)
            batch_keys.append(key)

            # Process batch when we hit the batch size
            if len(batch_keys) >= pipeline_batch_size:
                ttls = pipeline.execute()

                # Process TTL results
                for ttl in ttls:
                    total_keys += 1

                    if ttl <= 0:
                        ttl_buckets["expired"] += 1
                    elif ttl <= 3600:
                        ttl_buckets["expires_1h"] += 1
                    elif ttl <= 86400:
                        ttl_buckets["expires_24h"] += 1
                    elif ttl <= 604800:
                        ttl_buckets["expires_7d"] += 1
                    else:
                        ttl_buckets["expires_later"] += 1

                # Reset for next batch
                batch_keys = []
                pipeline = redis_client.pipeline(transaction=False)

        # Process remaining keys in the last batch
        if batch_keys:
            ttls = pipeline.execute()

            for ttl in ttls:
                total_keys += 1

                if ttl <= 0:
                    ttl_buckets["expired"] += 1
                elif ttl <= 3600:
                    ttl_buckets["expires_1h"] += 1
                elif ttl <= 86400:
                    ttl_buckets["expires_24h"] += 1
                elif ttl <= 604800:
                    ttl_buckets["expires_7d"] += 1
                else:
                    ttl_buckets["expires_later"] += 1

        # Sample memory usage for a subset of keys (up to sample_limit)
        # Use a second scan with pipelining for memory sampling
        if total_keys > 0:
            pipeline = redis_client.pipeline(transaction=False)
            sampled_keys = 0

            for key in redis_client.scan_iter(match=config.redis_stats_pattern, count=100):
                if sampled_keys >= sample_limit:
                    break

                pipeline.memory_usage(key)
                sampled_keys += 1

            if sampled_keys > 0:
                try:
                    memory_results = pipeline.execute()
                    sample_sizes = [mem for mem in memory_results if mem is not None]
                except Exception as e:
                    logger.warning(f"Failed to sample memory usage for {config.log_prefix}", error=str(e))

        total_teams = Team.objects.count()
        coverage_percent = (total_keys / total_teams * 100) if total_teams else 0

        size_stats = {}
        estimated_total_bytes: int | None = None
        if sample_sizes:
            avg_size = statistics.mean(sample_sizes)
            estimated_total_bytes = int(avg_size * total_keys)

            size_stats = {
                "sample_count": len(sample_sizes),
                "avg_size_bytes": int(avg_size),
                "median_size_bytes": int(statistics.median(sample_sizes)),
                "min_size_bytes": min(sample_sizes),
                "max_size_bytes": max(sample_sizes),
                "estimated_total_mb": round(estimated_total_bytes / (1024 * 1024), 2),
            }

        # Get expiry tracking count using ZCARD (O(1) operation)
        expiry_tracked_count = 0
        if config.hypercache.expiry_sorted_set_key:
            expiry_tracked_count = redis_client.zcard(config.hypercache.expiry_sorted_set_key)

        # Push metrics to Pushgateway for single-value display in Grafana
        push_hypercache_stats_metrics(
            namespace=config.namespace,
            coverage_percent=coverage_percent,
            entries_total=total_keys,
            expiry_tracked_total=expiry_tracked_count,
            size_bytes=estimated_total_bytes,
        )

        return {
            "total_cached": total_keys,
            "total_teams": total_teams,
            "expiry_tracked": expiry_tracked_count,
            "cache_coverage": f"{coverage_percent:.1f}%",
            "cache_coverage_percent": coverage_percent,
            "ttl_distribution": ttl_buckets,
            "size_statistics": size_stats,
            "namespace": config.hypercache.namespace,
            "note": f"Run 'python manage.py {config.management_command_name}' for detailed analysis",
        }

    except Exception as e:
        logger.exception(f"Error getting {config.log_prefix} stats", error=str(e))
        return {
            "error": str(e),
            "namespace": config.hypercache.namespace,
        }


def batch_check_expiry_tracking(
    teams: list[Team],
    config: HyperCacheManagementConfig,
) -> dict[str | int, bool]:
    """
    Check if teams are tracked in the expiry sorted set using pipelining.

    Uses Redis ZSCORE in a pipeline to efficiently check multiple teams
    in a single network round trip per batch.

    Args:
        teams: List of Team objects to check
        config: HyperCache management config

    Returns:
        Dict mapping team identifier (api_token or id) to True (tracked) or False (not tracked)
    """
    if not config.hypercache.expiry_sorted_set_key:
        # No expiry tracking configured - treat all teams as tracked
        return {config.hypercache.get_cache_identifier(team): True for team in teams}

    redis_client = get_client(config.hypercache.redis_url)
    results: dict[str | int, bool] = {}

    for i in range(0, len(teams), REDIS_PIPELINE_BATCH_SIZE):
        batch = teams[i : i + REDIS_PIPELINE_BATCH_SIZE]
        pipeline = redis_client.pipeline(transaction=False)
        identifiers: list[str | int] = []

        for team in batch:
            identifier = config.hypercache.get_cache_identifier(team)
            identifiers.append(identifier)
            pipeline.zscore(config.hypercache.expiry_sorted_set_key, str(identifier))

        scores = pipeline.execute()

        for identifier, score in zip(identifiers, scores):
            # ZSCORE returns None if member doesn't exist
            results[identifier] = score is not None

    return results
