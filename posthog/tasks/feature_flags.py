import time

from django.conf import settings
from django.db import DatabaseError, OperationalError, transaction
from django.db.models import Count, F, Func, IntegerField, Max, Sum, TextField
from django.db.models.functions import Cast

import structlog
from celery import Task, shared_task
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feature_flag.flags_cache import (
    cleanup_stale_expiry_tracking,
    get_cache_stats,
    refresh_expiring_flags_caches,
    update_flags_cache,
)
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
    update_flag_caches,
)
from posthog.models.person.util import (
    count_hash_key_overrides_above_threshold,
    delete_hash_key_overrides_by_ids,
    get_colliding_hash_key_override_ids,
    get_hash_key_override_ids,
    rename_hash_key_overrides_by_ids,
)
from posthog.models.team import Team
from posthog.person_db_router import PERSONS_DB_FOR_WRITE
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

logger = structlog.get_logger(__name__)

# Override-cleanup tasks bound their work to teams whose row count for the
# target (team_id, feature_flag_key) tuple is below this threshold. The
# table's heaviest team holds ~40% of all rows, so an unbounded UPDATE on a
# rename for that team would scan hundreds of millions of rows on the persons
# DB — the same path that serves /decide. Skipped renames/deletes are picked
# up by the management-command backfill (separate PR).
HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD = 50_000

# Per-batch cap for the chunked UPDATE/DELETE loops below. Each batch runs
# inside its own transaction so row-level locks are released between chunks
# and concurrent INSERTs from set_feature_flag_hash_key_overrides aren't
# blocked for the duration of the whole task.
HASH_KEY_OVERRIDE_BATCH_SIZE = 10_000

# Total retries (initial attempt + max_retries). Used to detect "this is the
# last attempt" so we can capture to Sentry before the task gives up.
HASH_KEY_OVERRIDE_MAX_RETRIES = 3


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
def update_team_flags_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    update_flag_caches(team)


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
def update_team_service_flags_cache(team_id: int) -> None:
    """
    Update the service flags cache for a specific team.

    This task is triggered when feature flags change or when teams are created,
    ensuring the feature-flags service has fresh data in HyperCache.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.debug("Team does not exist for service flags cache update", team_id=team_id)
        HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace="feature_flags", operation="update", result="failure").inc()
        return

    success = update_flags_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="feature_flags", operation="update", result="success" if success else "failure"
    ).inc()


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def refresh_expiring_flags_cache_entries(self: PushGatewayTask) -> None:
    """
    Periodic task to refresh flags caches before they expire.

    This task runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.

    For initial cache build or schema migrations, use the management command:
        python manage.py warm_flags_cache
    """

    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags cache refresh")
        return

    # Create metrics gauges for this task run
    successful_gauge = Gauge(
        "posthog_flags_cache_refresh_successful_count",
        "Number of flags caches successfully refreshed",
        registry=self.metrics_registry,
    )
    failed_gauge = Gauge(
        "posthog_flags_cache_refresh_failed_count",
        "Number of flags caches that failed to refresh",
        registry=self.metrics_registry,
    )

    start_time = time.time()
    logger.info(
        "Starting flags cache sync",
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    successful, failed = refresh_expiring_flags_caches(
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    # Record metrics
    successful_gauge.set(successful)
    failed_gauge.set(failed)

    # Note: Teams processed metrics are pushed to Pushgateway by
    # cache_expiry_manager.refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

    # Scan after refresh for metrics (pushes to Pushgateway via get_cache_stats)
    stats_after = get_cache_stats()

    duration = time.time() - start_time

    logger.info(
        "Completed flags cache refresh",
        successful_refreshes=successful,
        failed_refreshes=failed,
        total_cached=stats_after.get("total_cached", 0),
        total_teams=stats_after.get("total_teams", 0),
        cache_coverage=stats_after.get("cache_coverage", "unknown"),
        ttl_distribution=stats_after.get("ttl_distribution", {}),
        duration_seconds=duration,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def cleanup_stale_flags_expiry_tracking_task(self: PushGatewayTask) -> None:
    """
    Periodic task to clean up stale entries in the flags cache expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags expiry tracking cleanup")
        return

    entries_cleaned_gauge = Gauge(
        "posthog_cleanup_stale_flags_expiry_entries_cleaned",
        "Number of stale expiry tracking entries cleaned up",
        registry=self.metrics_registry,
    )

    removed_count = cleanup_stale_expiry_tracking()
    entries_cleaned_gauge.set(removed_count)
    logger.info("Completed flags expiry tracking cleanup", removed_count=removed_count)


def _set_ranked_team_gauge(gauge: Gauge, rows: list[dict], value_key: str) -> None:
    """Set gauge values for a ranked list of team metrics."""
    for rank, row in enumerate(rows, start=1):
        gauge.labels(
            rank=str(rank),
            team_id=str(row["team_id"]),
            team_name=row["team__name"] or "Unknown",
        ).set(row[value_key] or 0)


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def compute_feature_flag_metrics(self: PushGatewayTask) -> None:
    """
    Compute and push feature flag metrics for Grafana dashboards.

    Metrics:
    - posthog_feature_flag_team_flag_count: Top 5 teams by active flag count
    - posthog_feature_flag_team_largest_flag_bytes: OCTET_LENGTH for top 5 teams (ranked by pg_column_size)
    - posthog_feature_flag_team_largest_flag_pg_bytes: pg_column_size for top 5 teams
    - posthog_feature_flag_team_total_size_bytes: OCTET_LENGTH for top 5 teams (ranked by pg_column_size)
    - posthog_feature_flag_team_total_size_pg_bytes: pg_column_size for top 5 teams

    Uses a two-phase query approach for size metrics:
    - Phase 1: Fast ranking with pg_column_size to select and rank the top 5 teams
    - Phase 2: Compute both OCTET_LENGTH and pg_column_size for those teams

    Both metrics use pg_column_size ranking for consistency. Reports both values because:
    - pg_column_size: PostgreSQL storage footprint (TOAST-compressed)
    - OCTET_LENGTH: Text representation size of the filters field
    """
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        logger.debug("Pushgateway not configured, skipping feature flag metrics computation")
        return

    flag_count_gauge = Gauge(
        "posthog_feature_flag_team_flag_count",
        "Number of active feature flags per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    largest_flag_gauge = Gauge(
        "posthog_feature_flag_team_largest_flag_bytes",
        "Text representation size of the largest feature flag filter per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    largest_flag_pg_gauge = Gauge(
        "posthog_feature_flag_team_largest_flag_pg_bytes",
        "PostgreSQL storage size of the largest feature flag filter per team (top 5, pg_column_size)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    total_size_gauge = Gauge(
        "posthog_feature_flag_team_total_size_bytes",
        "Total text representation size of all feature flag filters per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    total_size_pg_gauge = Gauge(
        "posthog_feature_flag_team_total_size_pg_bytes",
        "PostgreSQL total storage size of all feature flag filters per team (top 5, pg_column_size)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    base_qs = FeatureFlag.objects.filter(active=True)

    # Top 5 by flag count (secondary sort by team_id for deterministic ordering on ties)
    top_by_count = list(
        base_qs.values("team_id", "team__name").annotate(flag_count=Count("id")).order_by("-flag_count", "team_id")[:5]
    )

    # Size expressions
    pg_size = Func(F("filters"), function="pg_column_size", output_field=IntegerField())
    octet_size = Func(Cast(F("filters"), TextField()), function="OCTET_LENGTH", output_field=IntegerField())

    # Phase 1: Fast ranking with pg_column_size for "largest flag" metric
    top_largest_ranking = list(
        base_qs.annotate(pg_size=pg_size)
        .values("team_id")
        .annotate(max_pg_size=Max("pg_size"))
        .order_by("-max_pg_size", "team_id")[:5]
    )
    top_largest_team_ids = [t["team_id"] for t in top_largest_ranking]

    # Phase 2: Compute both metrics for top 5 teams, ordered by pg_column_size (Phase 1 ranking)
    top_by_largest = list(
        base_qs.filter(team_id__in=top_largest_team_ids)
        .annotate(filters_size=octet_size, pg_size=pg_size)
        .values("team_id", "team__name")
        .annotate(largest_flag_size=Max("filters_size"), largest_flag_pg_size=Max("pg_size"))
        .order_by("-largest_flag_pg_size", "team_id")
    )

    # Phase 1: Fast ranking with pg_column_size for "total size" metric
    top_total_ranking = list(
        base_qs.annotate(pg_size=pg_size)
        .values("team_id")
        .annotate(sum_pg_size=Sum("pg_size"))
        .order_by("-sum_pg_size", "team_id")[:5]
    )
    top_total_team_ids = [t["team_id"] for t in top_total_ranking]

    # Phase 2: Compute both metrics for top 5 teams, ordered by pg_column_size (Phase 1 ranking)
    top_by_total = list(
        base_qs.filter(team_id__in=top_total_team_ids)
        .annotate(filters_size=octet_size, pg_size=pg_size)
        .values("team_id", "team__name")
        .annotate(total_size=Sum("filters_size"), total_pg_size=Sum("pg_size"))
        .order_by("-total_pg_size", "team_id")
    )

    _set_ranked_team_gauge(flag_count_gauge, top_by_count, "flag_count")
    _set_ranked_team_gauge(largest_flag_gauge, top_by_largest, "largest_flag_size")
    _set_ranked_team_gauge(largest_flag_pg_gauge, top_by_largest, "largest_flag_pg_size")
    _set_ranked_team_gauge(total_size_gauge, top_by_total, "total_size")
    _set_ranked_team_gauge(total_size_pg_gauge, top_by_total, "total_pg_size")

    logger.info(
        "Computed feature flag metrics",
        top_flag_count=top_by_count[0]["flag_count"] if top_by_count else 0,
        top_largest_flag_bytes=top_by_largest[0]["largest_flag_size"] if top_by_largest else 0,
        top_largest_flag_pg_bytes=top_by_largest[0]["largest_flag_pg_size"] if top_by_largest else 0,
        top_total_size_bytes=top_by_total[0]["total_size"] if top_by_total else 0,
        top_total_size_pg_bytes=top_by_total[0]["total_pg_size"] if top_by_total else 0,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def refresh_expiring_flag_definitions_cache_entries(self: PushGatewayTask) -> None:
    """
    Periodic task to refresh flag definitions caches before they expire.

    Refreshes both with-cohorts and without-cohorts cache variants.
    Runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.
    """

    from posthog.storage.cache_expiry_manager import refresh_expiring_caches

    successful_gauge = Gauge(
        "posthog_flag_definitions_cache_refresh_successful_count",
        "Number of flag definitions caches successfully refreshed",
        registry=self.metrics_registry,
    )
    failed_gauge = Gauge(
        "posthog_flag_definitions_cache_refresh_failed_count",
        "Number of flag definitions caches that failed to refresh",
        registry=self.metrics_registry,
    )

    start_time = time.time()
    logger.info(
        "Starting flag definitions cache sync",
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    total_successful = 0
    total_failed = 0

    # Refresh both cache variants
    for config, variant_name in [
        (FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with-cohorts"),
        (FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without-cohorts"),
    ]:
        try:
            successful, failed = refresh_expiring_caches(
                config=config,
                ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
                limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
            )
            total_successful += successful
            total_failed += failed
            logger.info(
                "Completed flag definitions cache refresh for variant",
                variant=variant_name,
                successful_refreshes=successful,
                failed_refreshes=failed,
            )
        except Exception as e:
            logger.exception(
                "Failed to refresh flag definitions cache variant",
                variant=variant_name,
                error=str(e),
            )
            total_failed += 1

    successful_gauge.set(total_successful)
    failed_gauge.set(total_failed)

    duration = time.time() - start_time
    logger.info(
        "Completed flag definitions cache refresh",
        total_successful_refreshes=total_successful,
        total_failed_refreshes=total_failed,
        duration_seconds=duration,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def cleanup_stale_flag_definitions_expiry_tracking_task(self: PushGatewayTask) -> None:
    """
    Periodic task to clean up stale entries in the flag definitions cache expiry tracking sorted sets.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    Cleans up both with-cohorts and without-cohorts sorted sets.
    """

    from posthog.storage.cache_expiry_manager import cleanup_stale_expiry_tracking

    entries_cleaned_gauge = Gauge(
        "posthog_cleanup_stale_flag_definitions_expiry_entries_cleaned",
        "Number of stale flag definitions expiry tracking entries cleaned up",
        registry=self.metrics_registry,
    )

    total_removed = 0
    configs = [
        (FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with-cohorts"),
        (FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without-cohorts"),
    ]

    for config, variant_name in configs:
        try:
            removed_count = cleanup_stale_expiry_tracking(config)
            total_removed += removed_count
            logger.info(
                "Completed flag definitions expiry tracking cleanup for variant",
                variant=variant_name,
                removed_count=removed_count,
            )
        except Exception as e:
            logger.exception(
                "Failed to cleanup flag definitions expiry tracking for variant",
                variant=variant_name,
                error=str(e),
            )

    entries_cleaned_gauge.set(total_removed)
    logger.info("Completed flag definitions expiry tracking cleanup", total_removed_count=total_removed)


def _exceeds_large_team_threshold(team_id: int, feature_flag_key: str) -> bool:
    """Bounded probe — checks whether (team_id, feature_flag_key) holds more
    rows than ``HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD``. Stops scanning once
    the threshold is exceeded, so this stays cheap even on the heaviest teams.
    """
    return count_hash_key_overrides_above_threshold(team_id, feature_flag_key, HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD)


def _capture_if_final_attempt(celery_task: Task, exc: Exception, **context: object) -> None:
    """Send ``exc`` to Sentry/PostHog on the final retry so silent regressions
    surface in dashboards rather than only in retry logs. The caller always
    re-raises — this only adds the capture side-effect."""
    # ``request.retries`` is 0 on the first attempt and increments before each
    # retry, so it equals ``max_retries`` only on the very last attempt.
    if celery_task.request.retries >= HASH_KEY_OVERRIDE_MAX_RETRIES:
        capture_exception(exc, additional_properties=context)
        logger.exception(
            "hash_key_override_cleanup_retries_exhausted",
            **context,
        )


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    autoretry_for=(DatabaseError, OperationalError),
    retry_kwargs={"max_retries": HASH_KEY_OVERRIDE_MAX_RETRIES, "countdown": 60},
)
def rewrite_hash_key_overrides_for_flag(self: Task, team_id: int, old_key: str, new_key: str) -> None:
    """Rewrite ``FeatureFlagHashKeyOverride`` rows from ``old_key`` -> ``new_key``
    for one team.

    Fired on commit when a feature flag's key is renamed via the API. Without this,
    override rows still reference the old key and become orphaned (silently
    inflating the table forever).

    The rewrite mirrors the "first override wins" semantics from
    ``set_feature_flag_hash_key_overrides`` (INSERT ... ON CONFLICT DO NOTHING):
    if a person already has a row under ``new_key``, the corresponding
    ``old_key`` row is dropped instead of renamed, so the bulk UPDATE never
    collides with the unique constraint on (team, person, feature_flag_key).

    Idempotent: re-running with the same args is a no-op (the second run finds no
    rows under ``old_key``). Safe to retry on transient DB errors.
    """
    if old_key == new_key:
        return

    if _exceeds_large_team_threshold(team_id, old_key):
        # Defer to the offline backfill management command (separate PR). The
        # write-time path is best-effort; the backfill is the safety net.
        logger.warning(
            "rewrite_hash_key_overrides_for_flag_skipped_large_team",
            team_id=team_id,
            old_key=old_key,
            new_key=new_key,
            threshold=HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD,
        )
        return

    try:
        total_pre_deleted = 0
        total_updated = 0

        # Step 1 — drop ``old_key`` rows for any person who already has a
        # ``new_key`` row, in batches so we don't hold locks on the full set.
        while True:
            with transaction.atomic(using=PERSONS_DB_FOR_WRITE):
                colliding_ids = get_colliding_hash_key_override_ids(
                    team_id, old_key, new_key, limit=HASH_KEY_OVERRIDE_BATCH_SIZE
                )
                if not colliding_ids:
                    break
                total_pre_deleted += delete_hash_key_overrides_by_ids(colliding_ids)

        # Step 2 — rename the surviving ``old_key`` rows in batches. With the
        # collisions cleared above, each batched UPDATE is collision-free.
        while True:
            with transaction.atomic(using=PERSONS_DB_FOR_WRITE):
                ids = get_hash_key_override_ids(team_id, old_key, limit=HASH_KEY_OVERRIDE_BATCH_SIZE)
                if not ids:
                    break
                total_updated += rename_hash_key_overrides_by_ids(ids, new_key=new_key)

        logger.info(
            "rewrite_hash_key_overrides_for_flag",
            team_id=team_id,
            old_key=old_key,
            new_key=new_key,
            rows_pre_deleted=total_pre_deleted,
            rows_updated=total_updated,
        )
    except (DatabaseError, OperationalError) as exc:
        _capture_if_final_attempt(
            self,
            exc,
            task="rewrite_hash_key_overrides_for_flag",
            team_id=team_id,
            old_key=old_key,
            new_key=new_key,
        )
        raise


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    autoretry_for=(DatabaseError, OperationalError),
    retry_kwargs={"max_retries": HASH_KEY_OVERRIDE_MAX_RETRIES, "countdown": 60},
)
def delete_hash_key_overrides_for_flag(self: Task, team_id: int, key: str) -> None:
    """Delete ``FeatureFlagHashKeyOverride`` rows for one (team, flag key) tuple.

    Fired on commit when a feature flag is soft-deleted via the API. Idempotent:
    re-running deletes nothing extra. Safe to retry on transient DB errors.
    """
    if _exceeds_large_team_threshold(team_id, key):
        logger.warning(
            "delete_hash_key_overrides_for_flag_skipped_large_team",
            team_id=team_id,
            key=key,
            threshold=HASH_KEY_OVERRIDE_LARGE_TEAM_THRESHOLD,
        )
        return

    try:
        total_deleted = 0
        while True:
            with transaction.atomic(using=PERSONS_DB_FOR_WRITE):
                ids = get_hash_key_override_ids(team_id, key, limit=HASH_KEY_OVERRIDE_BATCH_SIZE)
                if not ids:
                    break
                total_deleted += delete_hash_key_overrides_by_ids(ids)

        logger.info(
            "delete_hash_key_overrides_for_flag",
            team_id=team_id,
            key=key,
            rows_deleted=total_deleted,
        )
    except (DatabaseError, OperationalError) as exc:
        _capture_if_final_attempt(
            self,
            exc,
            task="delete_hash_key_overrides_for_flag",
            team_id=team_id,
            key=key,
        )
        raise
