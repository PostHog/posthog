import structlog
from celery import shared_task
from celery.canvas import chain
from sentry_sdk import capture_exception

from posthog.api.services.query import process_query_dict
from posthog.caching.utils import largest_teams
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.query_cache import QueryCacheManager
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import conversion_to_query_based
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, Insight

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, expires=60 * 60)
def schedule_warming_for_largest_teams_task():
    team_ids = largest_teams()

    logger.info("Warming insight cache: largest teams", team_ids=team_ids)

    teams = Team.objects.filter(pk__in=team_ids)

    if len(teams) == 0:  # For local development
        teams = Team.objects.all()[:10]

    for team in teams:
        insight_ids = QueryCacheManager.get_stale_insights(team_id=team.pk, limit=50)

        task_groups = chain(*(warm_insight_cache_task.si(insight_id) for insight_id in insight_ids))
        task_groups.apply_async()


@shared_task(ignore_result=True, expires=60 * 60)
def warm_insight_cache_task(insight_id: str):
    insight_id, dashboard_id = insight_id.split(":")
    insight = Insight.objects.get(pk=insight_id)
    dashboard = None

    tag_queries(team_id=insight.team_id, insight_id=insight.pk, trigger="warmingV2")
    if dashboard_id:
        tag_queries(dashboard_id=dashboard_id)
        dashboard = insight.dashboards.get(pk=dashboard_id)

    with conversion_to_query_based(insight):
        logger.info(f"Warming insight {insight.pk} for team {insight.team_id} and dashboard {dashboard_id}")

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
