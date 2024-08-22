from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Union

import structlog
from pydantic import BaseModel
from sentry_sdk import capture_exception

from posthog.api.services.query import ExecutionMode, process_query_dict
from posthog.caching.utils import ensure_is_date
from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_RETENTION,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    TRENDS_STICKINESS,
    FunnelVizType,
)
from posthog.decorators import CacheType
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import conversion_to_query_based
from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.logging.timing import timed
from posthog.models import (
    Dashboard,
    DashboardTile,
    EventDefinition,
    Filter,
    Insight,
    RetentionFilter,
    Team,
    User,
)
from posthog.models.filters import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.insight import generate_insight_filters_hash
from posthog.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.paths import Paths
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.trends import Trends
from posthog.schema import CacheMissResponse, DashboardFilter
from posthog.types import FilterType

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import InsightResult

CACHE_TYPE_TO_INSIGHT_CLASS = {
    CacheType.TRENDS: Trends,
    CacheType.STICKINESS: Stickiness,
    CacheType.RETENTION: Retention,
    CacheType.PATHS: Paths,
}

logger = structlog.get_logger(__name__)


def calculate_cache_key(target: Union[DashboardTile, Insight]) -> Optional[str]:
    insight: Optional[Insight] = target if isinstance(target, Insight) else target.insight
    dashboard: Optional[Dashboard] = target.dashboard if isinstance(target, DashboardTile) else None

    if insight is not None:
        with conversion_to_query_based(insight):
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


def get_cache_type_for_filter(cacheable: FilterType) -> CacheType:
    if cacheable.insight == INSIGHT_FUNNELS:
        return CacheType.FUNNEL
    elif cacheable.insight == INSIGHT_PATHS:
        return CacheType.PATHS
    elif cacheable.insight == INSIGHT_RETENTION:
        return CacheType.RETENTION
    elif (
        cacheable.insight == INSIGHT_TRENDS
        and isinstance(cacheable, StickinessFilter)
        and cacheable.shown_as == TRENDS_STICKINESS
    ) or cacheable.insight == INSIGHT_STICKINESS:
        return CacheType.STICKINESS
    else:
        return CacheType.TRENDS


def get_cache_type_for_query(cacheable: dict) -> CacheType:
    cache_type = None

    if cacheable.get("source"):
        cache_type = cacheable["source"].get("kind", None)
    elif cacheable.get("kind"):
        cache_type = cacheable["kind"]

    if cache_type is None:
        logger.error("could_not_determine_cache_type", cacheable=cacheable)
        raise Exception("Could not determine cache type. No query kind provided.")

    return cache_type


def get_cache_type(cacheable: Optional[FilterType] | Optional[dict]) -> CacheType:
    if isinstance(cacheable, dict):
        return get_cache_type_for_query(cacheable)
    elif cacheable is not None:
        # even though it appears to work mypy does not like
        # elif isinstance(cacheable, FilterType):
        # you should not, apparently, use isinstance with a Generic type
        # luckily if cacheable is not a dict it must be a filter
        return get_cache_type_for_filter(cacheable)
    else:
        logger.error("could_not_determine_cache_type_for_insight", cacheable=cacheable)
        raise Exception("Could not determine cache type. Must provide a filter or a query")


def calculate_for_query_based_insight(
    insight: Insight,
    *,
    dashboard: Optional[Dashboard] = None,
    execution_mode: ExecutionMode,
    user: Optional[User],
    filters_override: Optional[dict] = None,
) -> "InsightResult":
    from posthog.caching.fetch_from_cache import InsightResult, NothingInCacheResult
    from posthog.caching.insight_cache import update_cached_state

    tag_queries(team_id=insight.team_id, insight_id=insight.pk)
    if dashboard:
        tag_queries(dashboard_id=dashboard.pk)

    response = process_response = process_query_dict(
        insight.team,
        insight.query,
        dashboard_filters_json=(
            filters_override if filters_override is not None else dashboard.filters if dashboard is not None else None
        ),
        execution_mode=execution_mode,
        user=user,
        insight_id=insight.pk,
        dashboard_id=dashboard.pk if dashboard else None,
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
            insight.team_id,
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


def calculate_result_by_cache_type(cache_type: CacheType, filter: Filter, team: Team) -> list[dict[str, Any]]:
    if cache_type == CacheType.FUNNEL:
        return _calculate_funnel(filter, team)
    else:
        return _calculate_by_filter(filter, team, cache_type)


@timed("update_cache_item_timer.calculate_by_filter")
def _calculate_by_filter(filter: FilterType, team: Team, cache_type: CacheType) -> list[dict[str, Any]]:
    insight_class = CACHE_TYPE_TO_INSIGHT_CLASS[cache_type]

    if cache_type == CacheType.PATHS:
        result = insight_class(filter, team).run(filter, team)
    else:
        result = insight_class().run(filter, team)
    return result


@timed("update_cache_item_timer.calculate_funnel")
def _calculate_funnel(filter: Filter, team: Team) -> list[dict[str, Any]]:
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        result = ClickhouseFunnelTrends(team=team, filter=filter).run()
    elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
        result = ClickhouseFunnelTimeToConvert(team=team, filter=filter).run()
    else:
        funnel_order_class = get_funnel_order_class(filter)
        result = funnel_order_class(team=team, filter=filter).run()

    return result


def cache_includes_latest_events(
    payload: dict, filter: Union[RetentionFilter, StickinessFilter, PathFilter, Filter]
) -> bool:
    """
    event_definition has last_seen_at timestamp
    a cacheable has last_refresh

    if redis has cached result (is this always true with last_refresh?)
    and last_refresh is after last_seen_at for each event in the filter

    then there's no point re-calculating
    """

    last_refresh = ensure_is_date(payload.get("last_refresh", None))
    if last_refresh:
        event_names = _events_from_filter(filter)

        event_last_seen_at = list(
            EventDefinition.objects.filter(name__in=event_names).values_list("last_seen_at", flat=True)
        )
        if len(event_names) > 0 and len(event_names) == len(event_last_seen_at):
            return all(last_seen_at is not None and last_refresh >= last_seen_at for last_seen_at in event_last_seen_at)

    return False


def _events_from_filter(filter: Union[RetentionFilter, StickinessFilter, PathFilter, Filter]) -> list[str]:
    """
    If a filter only represents a set of events
    then we can use their last_seen_at to determine if the cache is up-to-date

    It would be tricky to extend that concept to other filters or to filters with actions,
    so for now we'll just return an empty list and can (dis?)prove that this mechanism is useful
    """
    try:
        if isinstance(filter, StickinessFilter) or isinstance(filter, Filter):
            if not filter.actions:
                return [str(e.id) for e in filter.events]

        return []
    except Exception as exc:
        logger.error(
            "update_cache_item.could_not_list_events_from_filter",
            exc=exc,
            exc_info=True,
        )
        capture_exception(exc)
        return []
