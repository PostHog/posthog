import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import structlog
from celery import group
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.expressions import F
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.celery import update_cache_item_task
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
from posthog.models import Dashboard, DashboardTile, Filter, Insight, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.paths import Paths
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.trends import Trends
from posthog.types import FilterType
from posthog.utils import generate_cache_key

PARALLEL_INSIGHT_CACHE = int(os.environ.get("PARALLEL_DASHBOARD_ITEM_CACHE", 5))

logger = structlog.get_logger(__name__)

CACHE_TYPE_TO_INSIGHT_CLASS = {
    CacheType.TRENDS: Trends,
    CacheType.STICKINESS: Stickiness,
    CacheType.RETENTION: Retention,
    CacheType.PATHS: Paths,
}


@timed("update_cache_item_timer")
def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> List[Dict[str, Any]]:
    filter_dict = json.loads(payload["filter"])
    team_id = int(payload["team_id"])
    team = Team.objects.get(pk=team_id)
    filter = get_filter(data=filter_dict, team=team)

    # Doing the filtering like this means we'll update _all_ Insights and DashboardTiles with the same filters hash
    insights_queryset = Insight.objects.filter(Q(team_id=team_id, filters_hash=key))
    dashboard_tiles_queryset = DashboardTile.objects.filter(insight__team_id=team_id, filters_hash=key)

    # at least one must return something, if they both return they will be identical
    insight_result = _update_cache_for_queryset(cache_type, filter, key, team, insights_queryset)
    tiles_result = _update_cache_for_queryset(cache_type, filter, key, team, dashboard_tiles_queryset)

    if tiles_result is not None:
        result = tiles_result
    elif insight_result is not None:
        result = insight_result
    else:
        dashboard_id = payload.get("dashboard_id", None)
        insight_id = payload.get("insight_id", "unknown")
        statsd.incr(
            "update_cache_item_no_results",
            tags={"team": team_id, "cache_key": key, "insight_id": insight_id, "dashboard_id": dashboard_id,},
        )
        # there is strong likelihood these querysets match no insights or dashboard tiles
        _mark_refresh_attempt_for(insights_queryset)
        _mark_refresh_attempt_for(dashboard_tiles_queryset)
        # so mark the item that triggered the update
        if insight_id != "unknown":
            _mark_refresh_attempt_for(
                Insight.objects.filter(id=insight_id)
                if not dashboard_id
                else DashboardTile.objects.filter(insight_id=insight_id, dashboard_id=dashboard_id)
            )
        return []

    return result


def _update_cache_for_queryset(
    cache_type: CacheType, filter: Filter, key: str, team: Team, queryset: QuerySet
) -> Optional[List[Dict[str, Any]]]:
    if not queryset.exists():
        return None

    queryset.update(refreshing=True)
    try:
        if cache_type == CacheType.FUNNEL:
            result = _calculate_funnel(filter, key, team)
        else:
            result = _calculate_by_filter(filter, key, team, cache_type)
        cache.set(
            key, {"result": result, "type": cache_type, "last_refresh": timezone.now()}, settings.CACHED_RESULTS_TTL
        )
    except Exception as e:
        statsd.incr("update_cache_item_error", tags={"team": team.id})
        _mark_refresh_attempt_for(queryset)
        raise e

    if result:
        statsd.incr("update_cache_item_success", tags={"team": team.id})
        queryset.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
    else:
        queryset.update(last_refresh=timezone.now(), refreshing=False)

    return result


def _mark_refresh_attempt_for(queryset: QuerySet) -> None:
    queryset.filter(refresh_attempt=None).update(refresh_attempt=0)
    queryset.update(refreshing=False, refresh_attempt=F("refresh_attempt") + 1)


def update_insight_cache(insight: Insight, dashboard: Optional[Dashboard]) -> List[Dict[str, Any]]:
    cache_key, cache_type, payload = insight_update_task_params(insight, dashboard)
    # check if the cache key has changed, usually because of a new default filter
    # there are three possibilities
    # 1) the insight is not being updated in a dashboard context
    #    --> so set its cache key if it doesn't match
    # 2) the insight is being updated in a dashboard context and the dashboard has different filters to the insight
    #    --> so set only the dashboard tile's filters_hash
    # 3) the insight is being updated in a dashboard context and the dashboard has matching or no filters
    #    --> so set the dashboard tile and the insight's filters hash

    should_update_insight_filters_hash = False
    should_update_dashboard_tile_filters_hash = False

    if not dashboard and insight.filters_hash and insight.filters_hash != cache_key:
        should_update_insight_filters_hash = True

    if dashboard:
        should_update_dashboard_tile_filters_hash = True
        if not dashboard.filters or dashboard.filters == insight.filters:
            should_update_insight_filters_hash = True

    if should_update_insight_filters_hash:
        insight.filters_hash = cache_key
        insight.save()

    if should_update_dashboard_tile_filters_hash:
        dashboard_tiles = DashboardTile.objects.filter(insight=insight, dashboard=dashboard,).exclude(
            filters_hash=cache_key
        )
        dashboard_tiles.update(filters_hash=cache_key)

    if should_update_insight_filters_hash or should_update_dashboard_tile_filters_hash:
        statsd.incr(
            "update_cache_item_set_new_cache_key",
            tags={
                "team": insight.team.id,
                "cache_key": cache_key,
                "insight_id": insight.id,
                "dashboard_id": None if not dashboard else dashboard.id,
            },
        )

    result = update_cache_item(cache_key, cache_type, payload)
    insight.refresh_from_db()
    return result


def get_cache_type(filter: FilterType) -> CacheType:
    if filter.insight == INSIGHT_FUNNELS:
        return CacheType.FUNNEL
    elif filter.insight == INSIGHT_PATHS:
        return CacheType.PATHS
    elif filter.insight == INSIGHT_RETENTION:
        return CacheType.RETENTION
    elif (
        filter.insight == INSIGHT_TRENDS
        and isinstance(filter, StickinessFilter)
        and filter.shown_as == TRENDS_STICKINESS
    ) or filter.insight == INSIGHT_STICKINESS:
        return CacheType.STICKINESS
    else:
        return CacheType.TRENDS


def update_cached_items() -> Tuple[int, int]:
    tasks = []

    # TODO: According to the metrics, on Cloud this is a huge list and needs to be improved
    dashboard_tiles = (
        DashboardTile.objects.filter(
            Q(
                Q(dashboard__sharingconfiguration__enabled=True)
                | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7))
            )
        )
        .exclude(dashboard__deleted=True)
        .exclude(insight__deleted=True)
        .exclude(insight__filters={})
        .exclude(Q(insight__refreshing=True) | Q(refreshing=True))
        .exclude(Q(insight__refresh_attempt__gt=2) | Q(refresh_attempt__gt=2))
        .select_related("insight", "dashboard")
        .order_by(F("last_refresh").asc(nulls_first=True), F("insight__last_refresh").asc(nulls_first=True))
    )

    cache_candidates = dashboard_tiles[0:PARALLEL_INSIGHT_CACHE]
    for dashboard_tile in cache_candidates:
        insight = dashboard_tile.insight
        try:
            cache_key, cache_type, payload = insight_update_task_params(insight, dashboard_tile.dashboard)
            tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))
        except Exception as e:
            # to avoid splitting the queryset above, update refresh attempt on both tile and insight
            insight.refresh_attempt = (insight.refresh_attempt or 0) + 1
            insight.save(update_fields=["refresh_attempt"])
            dashboard_tile.refresh_attempt = (dashboard_tile.refresh_attempt or 0) + 1
            dashboard_tile.save(update_fields=["refresh_attempt"])

            capture_exception(e)

    shared_insights = (
        Insight.objects.filter(sharingconfiguration__enabled=True)
        .exclude(deleted=True)
        .exclude(filters={})
        .exclude(refreshing=True)
        .exclude(refresh_attempt__gt=2)
        .order_by(F("last_refresh").asc(nulls_first=True))
    )

    for insight in shared_insights[0:PARALLEL_INSIGHT_CACHE]:
        try:
            cache_key, cache_type, payload = insight_update_task_params(insight)
            tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))
        except Exception as e:
            insight.refresh_attempt = (insight.refresh_attempt or 0) + 1
            insight.save(update_fields=["refresh_attempt"])
            capture_exception(e)

    statsd.gauge("update_cache_queue.never_refreshed", dashboard_tiles.filter(last_refresh=None).count())

    # how old is the next to be refreshed
    for candidate in cache_candidates:
        if candidate.last_refresh:
            dashboard_cache_age = (datetime.datetime.now(timezone.utc) - candidate.last_refresh).total_seconds()

            statsd.gauge(
                "update_cache_queue.dashboards_lag",
                round(dashboard_cache_age),
                tags={
                    "insight_id": candidate.insight_id,
                    "dashboard_id": candidate.dashboard_id,
                    "cache_key": candidate.filters_hash,
                },
            )

            if dashboard_cache_age > 1800:
                logger.error(
                    "insight_cache.waiting_for_more_than_thirty_minutes",
                    insight_id=candidate.insight.id,
                    dashboard_id=candidate.dashboard.id,
                    cache_key=candidate.filters_hash,
                    team_id=candidate.insight.team.id,
                )

    logger.info("update_cache_queue", length=len(tasks))
    taskset = group(tasks)
    taskset.apply_async()

    # this is the number of cacheable items that match the query
    queue_depth = dashboard_tiles.count() + shared_insights.count()
    statsd.gauge("update_cache_queue_depth.shared_insights", shared_insights.count())
    statsd.gauge("update_cache_queue_depth.dashboards", dashboard_tiles.count())
    statsd.gauge("update_cache_queue_depth", queue_depth)

    return len(tasks), queue_depth


def insight_update_task_params(insight: Insight, dashboard: Optional[Dashboard] = None) -> Tuple[str, CacheType, Dict]:
    filter = get_filter(data=insight.dashboard_filters(dashboard), team=insight.team)
    cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), insight.team_id))

    cache_type = get_cache_type(filter)
    payload = {
        "filter": filter.toJSON(),
        "team_id": insight.team_id,
        "insight_id": insight.id,
        "dashboard_id": None if not dashboard else dashboard.id,
    }

    return cache_key, cache_type, payload


@timed("update_cache_item_timer.calculate_by_filter")
def _calculate_by_filter(filter: FilterType, key: str, team: Team, cache_type: CacheType) -> List[Dict[str, Any]]:
    insight_class = CACHE_TYPE_TO_INSIGHT_CLASS[cache_type]

    if cache_type == CacheType.PATHS:
        result = insight_class(filter, team).run(filter, team)
    else:
        result = insight_class().run(filter, team)
    return result


@timed("update_cache_item_timer.calculate_funnel")
def _calculate_funnel(filter: Filter, key: str, team: Team) -> List[Dict[str, Any]]:
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        result = ClickhouseFunnelTrends(team=team, filter=filter).run()
    elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
        result = ClickhouseFunnelTimeToConvert(team=team, filter=filter).run()
    else:
        funnel_order_class = get_funnel_order_class(filter)
        result = funnel_order_class(team=team, filter=filter).run()

    return result
