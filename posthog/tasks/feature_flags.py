import time

from django.conf import settings
from django.db.models import Count, F, Func, IntegerField, Max, Sum, TextField
from django.db.models.functions import Cast

import structlog
from celery import shared_task
from prometheus_client import Gauge

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feature_flag.flags_cache import (
    cleanup_stale_expiry_tracking,
    get_cache_stats,
    refresh_expiring_flags_caches,
    update_flags_cache,
)
from posthog.models.feature_flag.local_evaluation import update_flag_caches
from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

logger = structlog.get_logger(__name__)


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


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
def sync_all_flags_cache() -> None:
    # Meant to ensure we have all flags cache in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_flags_cache.delay(team_id)


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def refresh_expiring_flags_cache_entries(self: PushGatewayTask) -> None:
    """
    Periodic task to refresh flags caches before they expire.

    This task runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.

    For initial cache build or schema migrations, use the management command:
        python manage.py warm_flags_cache [--invalidate-first]
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

    base_qs = FeatureFlag.objects.filter(deleted=False, active=True)

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
