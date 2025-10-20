from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import structlog
from pydantic import BaseModel

from posthog.schema import CacheMissResponse, DashboardFilter

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import ExecutionMode, process_query_dict
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.models import Dashboard, DashboardTile, Insight, Team, User
from posthog.models.insight import generate_insight_filters_hash
from posthog.schema_migrations.upgrade_manager import upgrade_query

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import InsightResult


logger = structlog.get_logger(__name__)


def calculate_cache_key(target: Union[DashboardTile, Insight]) -> Optional[str]:
    insight: Optional[Insight] = target if isinstance(target, Insight) else target.insight
    dashboard: Optional[Dashboard] = target.dashboard if isinstance(target, DashboardTile) else None

    if insight is not None:
        with upgrade_query(insight):
            if insight.query:
                query_runner = get_query_runner_or_none(insight.query, insight.team)
                if query_runner is None:
                    return None  # Uncacheable query-based insight
                if dashboard is not None and dashboard.filters:
                    query_runner.apply_dashboard_filters(DashboardFilter(**dashboard.filters))
                return query_runner.get_cache_key()

            if insight.filters:
                return generate_insight_filters_hash(insight, dashboard)

    return None


def calculate_for_query_based_insight(
    insight: Insight,
    *,
    team: Team,
    dashboard: Optional[Dashboard] = None,
    execution_mode: ExecutionMode,
    user: Optional[User],
    filters_override: Optional[dict] = None,
    variables_override: Optional[dict] = None,
    tile_filters_override: Optional[dict] = None,
) -> "InsightResult":
    from posthog.caching.fetch_from_cache import InsightResult, NothingInCacheResult
    from posthog.caching.insight_cache import update_cached_state

    tag_queries(team_id=team.id, insight_id=insight.pk)
    if dashboard:
        tag_queries(dashboard_id=dashboard.pk)

    dashboard_filters_json = (
        filters_override if filters_override is not None else dashboard.filters if dashboard is not None else None
    )

    variables_override_json = (
        variables_override if variables_override is not None else dashboard.variables if dashboard is not None else None
    )

    # Tile filters overrides all other filters
    if tile_filters_override is not None and tile_filters_override != {}:
        dashboard_filters_json = tile_filters_override
        variables_override_json = None

    response = process_response = process_query_dict(
        team,
        insight.query,
        dashboard_filters_json=dashboard_filters_json,
        variables_override_json=variables_override_json,
        execution_mode=execution_mode,
        user=user,
        insight_id=insight.pk,
        dashboard_id=dashboard.pk if dashboard else None,
        # QUERY_ASYNC provides extended max execution time for insight queries
        limit_context=LimitContext.QUERY_ASYNC,
    )

    if isinstance(process_response, BaseModel):
        response = process_response.model_dump(by_alias=True)

    assert isinstance(response, dict)

    if isinstance(process_response, CacheMissResponse):
        return NothingInCacheResult(cache_key=process_response.cache_key, query_status=response.get("query_status"))

    cache_key = response.get("cache_key")
    last_refresh = response.get("last_refresh")
    if isinstance(cache_key, str) and isinstance(last_refresh, datetime):
        update_cached_state(  # Updating the relevant InsightCachingState
            team.id,
            cache_key,
            last_refresh,
            result=None,  # Not caching the result here, since in HogQL this is the query runner's responsibility
        )

    return InsightResult(
        # Translating `QueryResponse` to legacy insights shape
        # The response may not be conformant with that, hence these are all `.get()`s
        result=response.get("results"),
        has_more=response.get("hasMore"),
        columns=response.get("columns"),
        last_refresh=last_refresh,
        cache_key=cache_key,
        is_cached=response.get("is_cached", False),
        timezone=response.get("timezone"),
        next_allowed_client_refresh=response.get("next_allowed_client_refresh"),
        cache_target_age=response.get("cache_target_age"),
        timings=response.get("timings"),
        query_status=response.get("query_status"),
        hogql=response.get("hogql"),
        types=response.get("types"),
    )
