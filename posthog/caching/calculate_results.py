from typing import Any, Dict, List, Optional, Tuple, Union

import structlog
from sentry_sdk import capture_exception

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
from posthog.logging.timing import timed
from posthog.models import (
    Dashboard,
    DashboardTile,
    EventDefinition,
    Filter,
    Insight,
    RetentionFilter,
    Team,
)
from posthog.models.filters import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.models.insight import generate_insight_cache_key
from posthog.queries.funnels import (
    ClickhouseFunnelTimeToConvert,
    ClickhouseFunnelTrends,
)
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.paths import Paths
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.trends import Trends
from posthog.types import FilterType

# ClickHouse query timeout in seconds
# From https://github.com/PostHog/posthog-cloud-infra/blob/master/ansible/config/clickhouse-users.xml#L11
# Keep in sync with the above!
CLICKHOUSE_MAX_EXECUTION_TIME = 180

CACHE_TYPE_TO_INSIGHT_CLASS = {
    CacheType.TRENDS: Trends,
    CacheType.STICKINESS: Stickiness,
    CacheType.RETENTION: Retention,
    CacheType.PATHS: Paths,
}

logger = structlog.get_logger(__name__)


def calculate_cache_key(target: Union[DashboardTile, Insight]) -> Optional[str]:
    insight = target if isinstance(target, Insight) else target.insight
    dashboard = target.dashboard if isinstance(target, DashboardTile) else None

    if insight is None or (not insight.filters and insight.query is None):
        return None

    return generate_insight_cache_key(insight, dashboard)


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


def get_cache_type_for_query(cacheable: Dict) -> CacheType:
    cache_type = None

    if cacheable.get("source"):
        cache_type = cacheable["source"].get("kind", None)
    elif cacheable.get("kind"):
        cache_type = cacheable["kind"]

    if cache_type is None:
        logger.error("could_not_determine_cache_type", cacheable=cacheable)
        raise Exception("Could not determine cache type. No query kind provided.")

    return cache_type


def get_cache_type(cacheable: Optional[FilterType] | Optional[Dict]) -> CacheType:
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


def calculate_result_by_insight(
    team: Team, insight: Insight, dashboard: Optional[Dashboard]
) -> Tuple[str, str, List | Dict]:
    """
    Calculates the result for an insight. If the insight is query based,
    it will use the query to calculate the result. Even if there is a filter present on the insight

    Eventually there will be no filter-based insights left and calculate_for_query_based_insight will be
    in-lined into this function
    """
    if insight.query is not None:
        return calculate_for_query_based_insight(team, insight, dashboard)
    else:
        return calculate_for_filter_based_insight(team, insight, dashboard)


def calculate_for_query_based_insight(
    team: Team, insight: Insight, dashboard: Optional[Dashboard]
) -> Tuple[str, str, List | Dict]:
    cache_key = generate_insight_cache_key(insight, dashboard)
    cache_type = get_cache_type(insight.query)

    tag_queries(
        team_id=team.pk,
        insight_id=insight.pk,
        cache_type=cache_type,
        cache_key=cache_key,
    )

    # local import to avoid circular reference
    from posthog.api.services.query import process_query

    # TODO need to properly check that hogql is enabled?
    return cache_key, cache_type, process_query(team, insight.query, True)


def calculate_for_filter_based_insight(
    team: Team, insight: Insight, dashboard: Optional[Dashboard]
) -> Tuple[str, str, List | Dict]:
    filter = get_filter(data=insight.dashboard_filters(dashboard), team=team)
    cache_key = generate_insight_cache_key(insight, dashboard)
    cache_type = get_cache_type(filter)

    tag_queries(
        team_id=team.pk,
        insight_id=insight.pk,
        cache_type=cache_type,
        cache_key=cache_key,
    )

    return cache_key, cache_type, calculate_result_by_cache_type(cache_type, filter, team)


def calculate_result_by_cache_type(cache_type: CacheType, filter: Filter, team: Team) -> List[Dict[str, Any]]:
    if cache_type == CacheType.FUNNEL:
        return _calculate_funnel(filter, team)
    else:
        return _calculate_by_filter(filter, team, cache_type)


@timed("update_cache_item_timer.calculate_by_filter")
def _calculate_by_filter(filter: FilterType, team: Team, cache_type: CacheType) -> List[Dict[str, Any]]:
    insight_class = CACHE_TYPE_TO_INSIGHT_CLASS[cache_type]

    if cache_type == CacheType.PATHS:
        result = insight_class(filter, team).run(filter, team)
    else:
        result = insight_class().run(filter, team)
    return result


@timed("update_cache_item_timer.calculate_funnel")
def _calculate_funnel(filter: Filter, team: Team) -> List[Dict[str, Any]]:
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        result = ClickhouseFunnelTrends(team=team, filter=filter).run()
    elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
        result = ClickhouseFunnelTimeToConvert(team=team, filter=filter).run()
    else:
        funnel_order_class = get_funnel_order_class(filter)
        result = funnel_order_class(team=team, filter=filter).run()

    return result


def cache_includes_latest_events(
    payload: Dict, filter: Union[RetentionFilter, StickinessFilter, PathFilter, Filter]
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


def _events_from_filter(filter: Union[RetentionFilter, StickinessFilter, PathFilter, Filter]) -> List[str]:
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
