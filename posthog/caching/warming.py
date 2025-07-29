import itertools
from datetime import timedelta, UTC, datetime
from collections.abc import Generator
from typing import Optional

from posthog.schema_migrations.upgrade_manager import upgrade_query
import structlog
from celery import shared_task
from celery.canvas import chain
from django.db.models import Q
from prometheus_client import Counter, Gauge
from posthog.exceptions_capture import capture_exception

from posthog.api.services.query import process_query_dict
from posthog.caching.utils import largest_teams
from posthog.clickhouse.query_tagging import tag_queries, Feature
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.query_cache import QueryCacheManager
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, Insight, DashboardTile
from posthog.tasks.utils import CeleryQueue
from posthog.ph_client import ph_scoped_capture
import posthoganalytics


logger = structlog.get_logger(__name__)

STALE_INSIGHTS_GAUGE = Gauge(
    "posthog_cache_warming_stale_insights_gauge",
    "Number of stale insights present",
    ["team_id"],
)
PRIORITY_INSIGHTS_COUNTER = Counter(
    "posthog_cache_warming_priority_insights",
    "Number of priority insights warmed",
    ["team_id", "dashboard", "is_cached"],
)

LAST_VIEWED_THRESHOLD = timedelta(days=7)
SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD = timedelta(days=3)


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


def insights_to_keep_fresh(team: Team, shared_only: bool = False) -> Generator[tuple[int, Optional[int]], None, None]:
    """
    This is the place to decide which insights should be kept warm for the provided team.
    The reasoning is that this will be a yes or no decision. If we need to keep it warm, we try our best
    to not let the cache go stale. There isn't any middle ground, like trying to refresh it once a day, since
    that would be like clock that's only right twice a day.
    """
    # for shared insights, use a lower cut off
    threshold = datetime.now(UTC) - (
        LAST_VIEWED_THRESHOLD if not shared_only else SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD
    )

    QueryCacheManager.clean_up_stale_insights(team_id=team.pk, threshold=threshold)

    # get all insights currently in the cache for the team
    combos = QueryCacheManager.get_stale_insights(team_id=team.pk, limit=500)

    STALE_INSIGHTS_GAUGE.labels(team_id=team.pk).set(len(combos))

    dashboard_q_filter = Q()
    insight_ids_single = set()

    for insight_id, dashboard_id in (combo.split(":") for combo in combos):
        if dashboard_id:
            dashboard_q_filter |= Q(insight_id=insight_id, dashboard_id=dashboard_id)
        else:
            insight_ids_single.add(insight_id)

    if insight_ids_single:
        single_insights = team.insight_set.filter(
            insightviewed__last_viewed_at__gte=threshold,
            pk__in=insight_ids_single,
        )
        if shared_only:
            single_insights = single_insights.filter(sharingconfiguration__enabled=True)

        for single_insight_id in single_insights.distinct().values_list("id", flat=True):
            yield single_insight_id, None

    if not dashboard_q_filter:
        return

    if shared_only:
        dashboard_q_filter &= Q(dashboard__sharingconfiguration__enabled=True)

    dashboard_tiles = (
        DashboardTile.objects.filter(dashboard__last_accessed_at__gte=threshold)
        .filter(dashboard_q_filter)
        .distinct()
        .values_list("insight_id", "dashboard_id")
    )
    yield from dashboard_tiles


@shared_task(ignore_result=True, expires=60 * 15)
def schedule_warming_for_teams_task():
    """
    Runs every hour and schedule warming for all insights (picked from insights_to_cache)
    for each team enabled for cache warming.

    We trigger recalculation using ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    so even though we might pick all insights for a team to recalculate,
    only the stale ones (determined by `staleness_threshold_map`) get recalculated.
    """
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
        insight = Insight.objects.get(pk=insight_id)
    except Insight.DoesNotExist:
        logger.info(f"Warming insight cache failed 404 insight not found: {insight_id}")
        return

    dashboard = None

    tag_queries(team_id=insight.team_id, insight_id=insight.pk, trigger="warmingV2", feature=Feature.CACHE_WARMUP)
    if dashboard_id:
        tag_queries(dashboard_id=dashboard_id)
        dashboard = insight.dashboards.filter(pk=dashboard_id).first()

    with upgrade_query(insight):
        logger.info(f"Warming insight cache: {insight.pk} for team {insight.team_id} and dashboard {dashboard_id}")

        try:
            results = process_query_dict(
                insight.team,
                insight.query,
                dashboard_filters_json=dashboard.filters if dashboard is not None else None,
                # We need an execution mode with recent cache:
                # - in case someone refreshed after this task was triggered
                # - if insight + dashboard combinations have the same cache key, we prevent needless recalculations
                limit_context=LimitContext.QUERY_ASYNC,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
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
