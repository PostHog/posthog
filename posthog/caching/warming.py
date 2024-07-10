from datetime import timedelta, UTC, datetime
from collections.abc import Generator
from typing import Optional

import structlog
from celery import shared_task
from celery.canvas import chain
from django.db.models import Q
from prometheus_client import Counter
from sentry_sdk import capture_exception

from posthog.api.services.query import process_query_dict
from posthog.caching.utils import largest_teams
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.query_cache import QueryCacheManager
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import conversion_to_query_based
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, Insight, DashboardTile

logger = structlog.get_logger(__name__)

STALE_INSIGHTS_COUNTER = Counter(
    "posthog_cache_warming_stale_insights", "Number of stale insights present", ["team_id"]
)
PRIORITY_INSIGHTS_COUNTER = Counter(
    "posthog_cache_warming_priority_insights", "Number of priority insights warmed", ["team_id", "dashboard"]
)

LAST_VIEWED_THRESHOLD = timedelta(days=7)


def priority_insights(team: Team) -> Generator[tuple[str, Optional[str]], None, None]:
    combos = QueryCacheManager.get_stale_insights(team_id=team.pk, limit=500)

    STALE_INSIGHTS_COUNTER.labels(team_id=team.pk).inc(len(combos))

    now = datetime.now(UTC)
    dashboard_q_filter = Q()
    insight_ids_single = set()

    for insight_id, dashboard_id in (combo.split(":") for combo in combos):
        if dashboard_id:
            dashboard_q_filter |= Q(insight_id=insight_id, dashboard_id=dashboard_id)
        else:
            insight_ids_single.add(insight_id)

    if insight_ids_single:
        single_insights = (
            team.insight_set.filter(
                insightviewed__last_viewed_at__gte=now - LAST_VIEWED_THRESHOLD, pk__in=insight_ids_single
            )
            .distinct()
            .values_list("id", flat=True)
        )
        for insight_id in single_insights:
            yield insight_id, None

    if not dashboard_q_filter:
        return

    dashboard_tiles = (
        DashboardTile.objects.filter(dashboard__last_accessed_at__gte=now - LAST_VIEWED_THRESHOLD)
        .filter(dashboard_q_filter)
        .distinct()
        .values_list("insight_id", "dashboard_id")
    )
    for insight_id, dashboard_id in dashboard_tiles:
        yield insight_id, int(dashboard_id)


@shared_task(ignore_result=True, expires=60 * 60)
def schedule_warming_for_teams_task():
    team_ids = largest_teams()

    logger.info("Warming insight cache: teams", team_ids=team_ids)

    teams = Team.objects.filter(pk__in=team_ids)

    if len(teams) == 0:  # For local development
        teams = Team.objects.all()[:10]

    for team in teams:
        insight_tuples = priority_insights(team)

        task_groups = chain(*(warm_insight_cache_task.si(*insight_tuple) for insight_tuple in insight_tuples))
        task_groups.apply_async()


@shared_task(ignore_result=True, expires=60 * 60)
def warm_insight_cache_task(insight_id: str, dashboard_id: str):
    insight = Insight.objects.get(pk=insight_id)
    dashboard = None

    tag_queries(team_id=insight.team_id, insight_id=insight.pk, trigger="warmingV2")
    if dashboard_id:
        tag_queries(dashboard_id=dashboard_id)
        dashboard = insight.dashboards.get(pk=dashboard_id)

    PRIORITY_INSIGHTS_COUNTER.labels(team_id=insight.team_id, dashboard="true" if dashboard_id else "false").inc()

    with conversion_to_query_based(insight):
        logger.info(f"Warming insight cache: {insight.pk} for team {insight.team_id} and dashboard {dashboard_id}")

        try:
            process_query_dict(
                insight.team,
                insight.query,
                dashboard_filters_json=dashboard.filters if dashboard is not None else None,
                # We can do recent cache in case someone refreshed after this task was triggered
                # All we want to achieve is keeping it warm
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )
        except Exception as e:
            capture_exception(e)
