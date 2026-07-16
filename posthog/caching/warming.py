import math
import itertools
from collections import Counter as CollectionCounter
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from django.db.models import Q

import structlog
import posthoganalytics
from celery import shared_task
from celery.canvas import chain
from prometheus_client import Counter, Gauge, Histogram

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import process_query_dict
from posthog.caching.utils import largest_teams
from posthog.clickhouse.query_tagging import Feature, get_team_query_tags, tag_queries
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.dashboards.backend.access import DashboardAccessMethod
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

STALE_INSIGHTS_GAUGE = Gauge(
    "posthog_cache_warming_stale_insights_gauge",
    "Number of stale insights present",
    ["team_id"],
    multiprocess_mode="max",
)
PRIORITY_INSIGHTS_COUNTER = Counter(
    "posthog_cache_warming_priority_insights",
    "Number of priority insights warmed",
    ["team_id", "dashboard", "is_cached"],
)
CACHE_WARMING_CANDIDATE_COUNTER = Counter(
    "posthog_cache_warming_candidates_total",
    "Cache warming candidates by access method and scheduling outcome",
    ["access_method", "outcome", "cache_miss_boost"],
)
CACHE_WARMING_PRIORITY_HISTOGRAM = Histogram(
    "posthog_cache_warming_priority_score",
    "Priority scores for selected cache warming candidates",
    ["access_method"],
    buckets=(1, 5, 10, 25, 50, 100, 200, 400, 800),
)

LAST_VIEWED_THRESHOLD = timedelta(days=7)
SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD = timedelta(days=3)
MAX_WARMING_CANDIDATES_PER_TEAM = 500
WARMING_CANDIDATE_POOL_SIZE = 2000
CACHE_MISS_BOOST = 300.0
CACHE_MISS_BOOST_THRESHOLD = timedelta(days=1)
DASHBOARD_CANDIDATE_QUERY_CHUNK_SIZE = 100

ACCESS_METHOD_WEIGHTS = {
    DashboardAccessMethod.HUMAN: 300.0,
    DashboardAccessMethod.EMBEDDED: 200.0,
    DashboardAccessMethod.API: 100.0,
}
ACCESS_METHOD_THRESHOLDS = {
    DashboardAccessMethod.HUMAN: LAST_VIEWED_THRESHOLD,
    DashboardAccessMethod.EMBEDDED: SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD,
    DashboardAccessMethod.API: timedelta(days=1),
}
ACCESS_RECENCY_BONUS = 40.0
ACCESS_FREQUENCY_BONUS = 40.0


@dataclass(frozen=True)
class WarmingCandidate:
    insight_id: int
    dashboard_id: int | None
    priority: float
    access_method: str
    has_cache_miss_boost: bool = False


def _parse_access_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dashboard_warming_priority(
    most_recent_access: object,
    last_accessed_at: datetime | None,
    *,
    current_time: datetime,
) -> tuple[float, str, bool]:
    best_priority = 0.0
    best_access_method = "none"
    best_has_cache_miss_boost = False
    latest_structured_access: datetime | None = None

    if isinstance(most_recent_access, dict):
        for access_method, weight in ACCESS_METHOD_WEIGHTS.items():
            access_record = most_recent_access.get(access_method.value)
            if not isinstance(access_record, dict):
                continue

            accessed_at = _parse_access_timestamp(access_record.get("timestamp"))
            priority = 0.0
            if accessed_at is not None:
                latest_structured_access = max(latest_structured_access or accessed_at, accessed_at)
                threshold = ACCESS_METHOD_THRESHOLDS[access_method]
                age = current_time - accessed_at
                if timedelta(0) <= age <= threshold:
                    count = access_record.get("count", 0)
                    normalized_count = count if isinstance(count, int) and count > 0 else 1
                    frequency_bonus = min(math.log2(normalized_count + 1), 4.0) / 4.0 * ACCESS_FREQUENCY_BONUS
                    recency_bonus = max(0.0, 1.0 - age / threshold) * ACCESS_RECENCY_BONUS
                    priority = weight + frequency_bonus + recency_bonus

            cache_miss_at = _parse_access_timestamp(access_record.get("last_cache_miss_at"))
            cache_miss_age = current_time - cache_miss_at if cache_miss_at is not None else None
            has_cache_miss_boost = (
                cache_miss_age is not None and timedelta(0) <= cache_miss_age < CACHE_MISS_BOOST_THRESHOLD
            )
            if has_cache_miss_boost and cache_miss_age is not None:
                miss_recency_multiplier = 1.0 - cache_miss_age / CACHE_MISS_BOOST_THRESHOLD
                priority += CACHE_MISS_BOOST * miss_recency_multiplier

            if priority > best_priority:
                best_priority = priority
                best_access_method = access_method.value
                best_has_cache_miss_boost = has_cache_miss_boost

    if last_accessed_at is not None and (
        latest_structured_access is None or last_accessed_at > latest_structured_access
    ):
        legacy_age = current_time - last_accessed_at
        if timedelta(0) <= legacy_age <= LAST_VIEWED_THRESHOLD:
            legacy_priority = (
                ACCESS_METHOD_WEIGHTS[DashboardAccessMethod.API]
                + max(0.0, 1.0 - legacy_age / LAST_VIEWED_THRESHOLD) * ACCESS_RECENCY_BONUS
            )
            if legacy_priority > best_priority:
                return legacy_priority, "legacy", False

    if best_priority > 0:
        return best_priority, best_access_method, best_has_cache_miss_boost

    return 0.0, "none", False


def teams_enabled_for_cache_warming() -> list[int]:
    enabled_team_ids = []

    for team_id, organization_id, uuid in Team.objects.values_list(
        "id",
        "organization_id",
        "uuid",
    ).iterator(chunk_size=1000):
        enabled = posthoganalytics.feature_enabled(
            "cache-warming",
            str(uuid),
            groups={
                "organization": str(organization_id),
                "project": str(team_id),
            },
            group_properties={
                "organization": {
                    "id": str(organization_id),
                },
                "project": {
                    "id": str(team_id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

        if enabled:
            enabled_team_ids.append(team_id)

    return enabled_team_ids


def insights_to_keep_fresh(team: Team, shared_only: bool = False) -> Generator[tuple[int, Optional[int]]]:
    """
    Rank stale insight and dashboard combinations for the provided team, then keep the
    highest-priority candidates inside the per-team warming budget.
    """
    # for shared insights, use a lower cut off
    threshold = datetime.now(UTC) - (
        LAST_VIEWED_THRESHOLD if not shared_only else SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD
    )

    QueryCacheManagerBase.clean_up_stale_insights(team_id=team.pk, threshold=threshold)

    # get all insights currently in the cache for the team
    combos = QueryCacheManagerBase.get_stale_insights(team_id=team.pk, limit=WARMING_CANDIDATE_POOL_SIZE)

    STALE_INSIGHTS_GAUGE.labels(team_id=team.pk).set(len(combos))

    dashboard_pairs: list[tuple[int, int]] = []
    insight_ids_single: set[int] = set()

    for raw_insight_id, raw_dashboard_id in (combo.split(":") for combo in combos):
        if raw_dashboard_id:
            dashboard_pairs.append((int(raw_insight_id), int(raw_dashboard_id)))
        else:
            insight_ids_single.add(int(raw_insight_id))

    candidates: list[WarmingCandidate] = []
    candidate_metric_counts: CollectionCounter[tuple[str, str, str]] = CollectionCounter()

    if insight_ids_single:
        single_insights = team.insight_set.filter(
            insightviewed__last_viewed_at__gte=threshold,
            pk__in=insight_ids_single,
        )
        if shared_only:
            single_insights = single_insights.filter(sharingconfiguration__enabled=True)

        for single_insight_id in single_insights.distinct().values_list("id", flat=True):
            candidates.append(
                WarmingCandidate(
                    insight_id=single_insight_id,
                    dashboard_id=None,
                    priority=ACCESS_METHOD_WEIGHTS[DashboardAccessMethod.HUMAN],
                    access_method=DashboardAccessMethod.HUMAN.value,
                )
            )

    if dashboard_pairs:
        current_time = datetime.now(UTC)
        for dashboard_pair_chunk in itertools.batched(
            dashboard_pairs, DASHBOARD_CANDIDATE_QUERY_CHUNK_SIZE, strict=False
        ):
            dashboard_q_filter = Q()
            for candidate_insight_id, candidate_dashboard_id in dashboard_pair_chunk:
                dashboard_q_filter |= Q(insight_id=candidate_insight_id, dashboard_id=candidate_dashboard_id)
            if shared_only:
                dashboard_q_filter &= Q(dashboard__sharingconfiguration__enabled=True)

            dashboard_tiles = (
                DashboardTile.objects.filter(dashboard_q_filter)
                .distinct()
                .values_list(
                    "insight_id",
                    "dashboard_id",
                    "dashboard__last_accessed_at",
                    "dashboard__most_recent_access",
                )
            )
            for tile_insight_id, tile_dashboard_id, last_accessed_at, most_recent_access in dashboard_tiles:
                priority, access_method, has_cache_miss_boost = _dashboard_warming_priority(
                    most_recent_access,
                    last_accessed_at,
                    current_time=current_time,
                )
                if priority <= 0:
                    candidate_metric_counts[(access_method, "ineligible", "false")] += 1
                    continue
                candidates.append(
                    WarmingCandidate(
                        insight_id=tile_insight_id,
                        dashboard_id=tile_dashboard_id,
                        priority=priority,
                        access_method=access_method,
                        has_cache_miss_boost=has_cache_miss_boost,
                    )
                )

    candidates.sort(key=lambda candidate: candidate.priority, reverse=True)
    for index, candidate in enumerate(candidates):
        outcome = "selected" if index < MAX_WARMING_CANDIDATES_PER_TEAM else "deprioritized"
        candidate_metric_counts[(candidate.access_method, outcome, str(candidate.has_cache_miss_boost).lower())] += 1
        if outcome == "deprioritized":
            continue
        CACHE_WARMING_PRIORITY_HISTOGRAM.labels(access_method=candidate.access_method).observe(candidate.priority)

    for (access_method, outcome, cache_miss_boost), count in candidate_metric_counts.items():
        CACHE_WARMING_CANDIDATE_COUNTER.labels(
            access_method=access_method,
            outcome=outcome,
            cache_miss_boost=cache_miss_boost,
        ).inc(count)

    for candidate in candidates[:MAX_WARMING_CANDIDATES_PER_TEAM]:
        yield candidate.insight_id, candidate.dashboard_id


@shared_task(ignore_result=True, expires=60 * 15)
@skip_team_scope_audit
def schedule_warming_for_teams_task():
    """
    Runs every hour and schedule warming for all insights (picked from insights_to_cache)
    for each team enabled for cache warming.

    We trigger recalculation using ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    so even though we might pick all insights for a team to recalculate,
    only the stale ones (determined by `staleness_threshold_map`) get recalculated.
    """
    from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info("kill_switch_on_skipping_cache_warming", level=kill_switch_level)
        return

    team_ids = largest_teams(limit=10)
    threshold = datetime.now(UTC) - LAST_VIEWED_THRESHOLD

    enabled_teams = Team.objects.filter(
        Q(pk__in=team_ids)
        | Q(extra_settings__insights_cache_warming=True)
        | Q(pk__in=teams_enabled_for_cache_warming())
    )
    teams_with_recently_viewed_shared = Team.objects.filter(
        Q(
            Q(sharingconfiguration__dashboard__last_accessed_at__gte=threshold)
            | Q(sharingconfiguration__insight__insightviewed__last_viewed_at__gte=threshold)
        ),
        sharingconfiguration__enabled=True,
    ).difference(enabled_teams)

    all_teams = itertools.chain(
        zip(enabled_teams, [False] * len(enabled_teams)),
        zip(teams_with_recently_viewed_shared, [True] * len(teams_with_recently_viewed_shared)),
    )

    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = datetime.now(UTC) + timedelta(minutes=50)

    with ph_scoped_capture() as capture_ph_event:
        for team, shared_only in all_teams:
            insight_tuples = list(insights_to_keep_fresh(team, shared_only=shared_only))

            capture_ph_event(
                distinct_id=str(team.uuid),
                event="cache warming - insights to cache",
                properties={
                    "count": len(insight_tuples),
                    "team_id": team.id,
                    "organization_id": team.organization_id,
                    "shared_only": shared_only,
                },
            )

            # We chain the task execution to prevent queries *for a single team* running at the same time
            chain(
                *(
                    warm_insight_cache_task.si(*insight_tuple).set(expires=expire_after)
                    for insight_tuple in insight_tuples
                )
            )()


@shared_task(
    queue=CeleryQueue.ANALYTICS_LIMITED.value,  # Important! Prevents Clickhouse from being overwhelmed
    ignore_result=True,
    expires=60 * 60,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=2,
    retry_backoff_max=3,
    max_retries=3,
)
def warm_insight_cache_task(insight_id: int, dashboard_id: Optional[int]):
    try:
        # nosemgrep: idor-lookup-without-team (Celery task, ID from internal scheduling)
        insight = Insight.objects.select_related("team__organization").get(pk=insight_id)
    except Insight.DoesNotExist:
        logger.info(f"Warming insight cache failed 404 insight not found: {insight_id}")
        return

    dashboard = None

    tag_queries(
        **get_team_query_tags(insight.team),
        insight_id=insight.pk,
        trigger="warmingV2",
        feature=Feature.CACHE_WARMUP,
    )
    if dashboard_id:
        tag_queries(dashboard_id=dashboard_id)
        dashboard = insight.dashboards.filter(pk=dashboard_id).first()

    with upgrade_query(insight):
        logger.info(f"Warming insight cache: {insight.pk} for team {insight.team_id} and dashboard {dashboard_id}")

        try:
            results = process_query_dict(
                insight.team,
                cast(dict[str, Any], insight.query),
                dashboard_filters_json=dashboard.filters if dashboard is not None else None,
                # We need an execution mode with recent cache:
                # - in case someone refreshed after this task was triggered
                # - if insight + dashboard combinations have the same cache key, we prevent needless recalculations
                limit_context=LimitContext.QUERY_ASYNC,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=insight.created_by,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
                analytics_props={"source": EventSource.CACHE_WARMING},
            )

            is_cached = getattr(results, "is_cached", False)

            PRIORITY_INSIGHTS_COUNTER.labels(
                team_id=insight.team_id,
                dashboard=dashboard_id is not None,
                is_cached=is_cached,
            ).inc()

            with ph_scoped_capture() as capture_ph_event:
                capture_ph_event(
                    distinct_id=str(insight.team.uuid),
                    event="cache warming - warming insight",
                    properties={
                        "insight_id": insight.pk,
                        "insight_short_id": insight.short_id,
                        "dashboard_id": dashboard_id,
                        "is_cached": is_cached,
                        "team_id": insight.team_id,
                        "organization_id": insight.team.organization_id,
                    },
                )

        except CHQueryErrorTooManySimultaneousQueries:
            raise
        except Exception as e:
            capture_exception(e)
