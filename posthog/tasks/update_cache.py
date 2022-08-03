import datetime
import json
from typing import Any, Dict, List, Optional, Tuple, Union

import structlog
from celery import group
from celery.canvas import Signature
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.expressions import F
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog.celery import update_cache_item_task
from posthog.client import sync_execute
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
from posthog.models.instance_setting import get_instance_setting
from posthog.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.paths import Paths
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.trends import Trends
from posthog.redis import get_client
from posthog.types import FilterType
from posthog.utils import generate_cache_key

RECENTLY_ACCESSED_TEAMS_REDIS_KEY = "INSIGHT_CACHE_UPDATE_RECENTLY_ACCESSED_TEAMS"

logger = structlog.get_logger(__name__)

CACHE_TYPE_TO_INSIGHT_CLASS = {
    CacheType.TRENDS: Trends,
    CacheType.STICKINESS: Stickiness,
    CacheType.RETENTION: Retention,
    CacheType.PATHS: Paths,
}

IN_A_DAY = 86_400


def active_teams() -> List[int]:
    """
    Teams are stored in a sorted set. [{team_id: score}, {team_id: score}].
    Their "score" is the number of seconds since last event.
    Lower is better.
    This lets us exclude teams not in the set as they don't have recent events.
    That is, if a team has not ingested events in the last seven days, why refresh its insights?
    And could let us process the teams in order of how recently they ingested events.
    This assumes that the list of active teams is small enough to reasonably load in one go.
    """
    redis = get_client()
    all_teams: List[Tuple[bytes, float]] = redis.zrange(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, 0, -1, withscores=True)
    if not all_teams:
        teams_by_recency = sync_execute(
            """
            SELECT team_id, date_diff('second', max(timestamp), now()) AS age
            FROM events
            WHERE timestamp > date_sub(DAY, 3, now()) AND timestamp < now()
            GROUP BY team_id
            ORDER BY age;
        """
        )
        if not teams_by_recency:
            return []
        redis.zadd(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, {team: score for team, score in teams_by_recency})
        redis.expire(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, IN_A_DAY)
        all_teams = teams_by_recency

    return [int(team) for team, _ in all_teams]


def update_cached_items() -> Tuple[int, int]:
    PARALLEL_INSIGHT_CACHE = get_instance_setting("PARALLEL_DASHBOARD_ITEM_CACHE")
    recent_teams = active_teams()

    tasks: List[Optional[Signature]] = []

    dashboard_tiles = (
        DashboardTile.objects.filter(insight__team_id__in=recent_teams)
        .filter(
            Q(dashboard__sharingconfiguration__enabled=True)
            | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7))
        )
        .filter(
            # no last refresh date or last refresh not in last three minutes
            Q(last_refresh__isnull=True)
            | Q(last_refresh__lt=timezone.now() - relativedelta(minutes=3))
        )
        .exclude(dashboard__deleted=True)
        .exclude(insight__deleted=True)
        .exclude(insight__filters={})
        .exclude(Q(insight__refreshing=True) | Q(refreshing=True))
        .exclude(Q(insight__refresh_attempt__gt=2) | Q(refresh_attempt__gt=2))
        .select_related("insight", "dashboard")
        .order_by(F("last_refresh").asc(nulls_first=True), F("insight__last_refresh").asc(nulls_first=True))
    )

    for dashboard_tile in dashboard_tiles[0:PARALLEL_INSIGHT_CACHE]:
        tasks.append(task_for_cache_update_candidate(dashboard_tile))

    shared_insights = (
        Insight.objects.filter(team_id__in=recent_teams)
        .filter(sharingconfiguration__enabled=True)
        .exclude(deleted=True)
        .exclude(filters={})
        .exclude(refreshing=True)
        .exclude(refresh_attempt__gt=2)
        .order_by(F("last_refresh").asc(nulls_first=True))
    )

    for insight in shared_insights[0:PARALLEL_INSIGHT_CACHE]:
        tasks.append(task_for_cache_update_candidate(insight))

    gauge_cache_update_candidates(dashboard_tiles, shared_insights)

    tasks = list(filter(None, tasks))
    group(tasks).apply_async()
    return len(tasks), dashboard_tiles.count() + shared_insights.count()


def task_for_cache_update_candidate(candidate: Union[DashboardTile, Insight]) -> Optional[Signature]:
    candidate_tile: Optional[DashboardTile] = None if isinstance(candidate, Insight) else candidate
    candidate_insight: Insight = candidate if isinstance(candidate, Insight) else candidate.insight
    candidate_dashboard: Optional[Dashboard] = None if isinstance(candidate, Insight) else candidate.dashboard

    try:
        cache_key, cache_type, payload = insight_update_task_params(candidate_insight, candidate_dashboard)
        update_filters_hash(cache_key, candidate_dashboard, candidate_insight)
        return update_cache_item_task.s(cache_key, cache_type, payload)
    except Exception as e:
        candidate_insight.refresh_attempt = (candidate_insight.refresh_attempt or 0) + 1
        candidate_insight.save(update_fields=["refresh_attempt"])
        if candidate_tile:
            candidate_tile.refresh_attempt = (candidate_tile.refresh_attempt or 0) + 1
            candidate_tile.save(update_fields=["refresh_attempt"])
        capture_exception(e)
        return None


def gauge_cache_update_candidates(dashboard_tiles: QuerySet, shared_insights: QuerySet) -> None:
    statsd.gauge("update_cache_queue.never_refreshed", dashboard_tiles.filter(last_refresh=None).count())
    oldest_previously_refreshed_tiles: List[DashboardTile] = list(dashboard_tiles.exclude(last_refresh=None)[0:10])
    ages = []
    for candidate_tile in oldest_previously_refreshed_tiles:
        dashboard_cache_age = (datetime.datetime.now(timezone.utc) - candidate_tile.last_refresh).total_seconds()

        tags = {
            "insight_id": candidate_tile.insight_id,
            "dashboard_id": candidate_tile.dashboard_id,
            "cache_key": candidate_tile.filters_hash,
        }
        statsd.gauge(
            "update_cache_queue.dashboards_lag", round(dashboard_cache_age), tags=tags,
        )
        ages.append({**tags, "age": round(dashboard_cache_age)})

    logger.info("update_cache_queue.seen_ages", ages=ages)

    # this is the number of cacheable items that match the query
    statsd.gauge("update_cache_queue_depth.shared_insights", shared_insights.count())
    statsd.gauge("update_cache_queue_depth.dashboards", dashboard_tiles.count())
    statsd.gauge("update_cache_queue_depth", dashboard_tiles.count() + shared_insights.count())


@timed("update_cache_item_timer")
def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> List[Dict[str, Any]]:
    dashboard_id = payload.get("dashboard_id", None)
    insight_id = payload.get("insight_id", "unknown")

    filter_dict = json.loads(payload["filter"])
    team_id = int(payload["team_id"])
    team = Team.objects.get(pk=team_id)
    filter = get_filter(data=filter_dict, team=team)

    insights_queryset = Insight.objects.filter(Q(team_id=team_id, filters_hash=key))
    insights_queryset.update(refreshing=True)
    dashboard_tiles_queryset = DashboardTile.objects.filter(insight__team_id=team_id, filters_hash=key)
    dashboard_tiles_queryset.update(refreshing=True)

    result = None
    try:
        if (dashboard_id and dashboard_tiles_queryset.exists()) or insights_queryset.exists():
            result = _update_cache_for_queryset(cache_type, filter, key, team)
    except Exception as e:
        statsd.incr("update_cache_item_error", tags={"team": team.id})
        _mark_refresh_attempt_for(insights_queryset)
        _mark_refresh_attempt_for(dashboard_tiles_queryset)
        with push_scope() as scope:
            scope.set_tag("cache_key", key)
            scope.set_tag("team_id", team.id)
            scope.set_tag("insight_id", insight_id)
            scope.set_tag("dashboard_id", dashboard_id)
            capture_exception(e)
        logger.error("update_cache_item_error", exc=e, exc_info=True, team_id=team.id, cache_key=key)
        raise e

    if result:
        statsd.incr("update_cache_item_success", tags={"team": team.id})
        insights_queryset.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
        dashboard_tiles_queryset.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
    else:
        insights_queryset.update(last_refresh=timezone.now(), refreshing=False)
        dashboard_tiles_queryset.update(last_refresh=timezone.now(), refreshing=False)
        statsd.incr(
            "update_cache_item_no_results",
            tags={"team": team_id, "cache_key": key, "insight_id": insight_id, "dashboard_id": dashboard_id,},
        )
        _mark_refresh_attempt_when_no_results(dashboard_id, dashboard_tiles_queryset, insight_id, insights_queryset)
        result = []

    logger.info(
        "update_insight_cache.processed_item",
        insight_id=payload.get("insight_id", None),
        dashboard_id=payload.get("dashboard_id", None),
        cache_key=key,
        has_results=len(result) > 0,
    )

    return result


def _mark_refresh_attempt_when_no_results(
    dashboard_id: Optional[int],
    dashboard_tiles_queryset: QuerySet,
    insight_id: Union[int, str],
    insights_queryset: QuerySet,
) -> None:
    if insights_queryset.exists() or dashboard_tiles_queryset.exists():
        _mark_refresh_attempt_for(insights_queryset)
        _mark_refresh_attempt_for(dashboard_tiles_queryset)
    else:
        if insight_id != "unknown":
            _mark_refresh_attempt_for(
                Insight.objects.filter(id=insight_id)
                if not dashboard_id
                else DashboardTile.objects.filter(insight_id=insight_id, dashboard_id=dashboard_id)
            )


def _update_cache_for_queryset(
    cache_type: CacheType, filter: Filter, key: str, team: Team
) -> Optional[List[Dict[str, Any]]]:

    if cache_type == CacheType.FUNNEL:
        result = _calculate_funnel(filter, key, team)
    else:
        result = _calculate_by_filter(filter, key, team, cache_type)

    cache.set(key, {"result": result, "type": cache_type, "last_refresh": timezone.now()}, settings.CACHED_RESULTS_TTL)

    return result


def _mark_refresh_attempt_for(queryset: QuerySet) -> None:
    queryset.filter(refresh_attempt=None).update(refresh_attempt=0)
    queryset.update(refreshing=False, refresh_attempt=F("refresh_attempt") + 1)


def synchronously_update_insight_cache(insight: Insight, dashboard: Optional[Dashboard]) -> List[Dict[str, Any]]:
    cache_key, cache_type, payload = insight_update_task_params(insight, dashboard)
    update_filters_hash(cache_key, dashboard, insight)
    result = update_cache_item(cache_key, cache_type, payload)
    insight.refresh_from_db()
    return result


def update_filters_hash(cache_key: str, dashboard: Optional[Dashboard], insight: Insight) -> None:
    """ check if the cache key has changed, usually because of a new default filter
    # there are three possibilities
    # 1) the insight is not being updated in a dashboard context
    #    --> so set its cache key if it doesn't match
    # 2) the insight is being updated in a dashboard context and the dashboard has different filters to the insight
    #    --> so set only the dashboard tile's filters_hash
    # 3) the insight is being updated in a dashboard context and the dashboard has matching or no filters
    #    --> so set the dashboard tile and the insight's filters hash"""

    should_update_insight_filters_hash = False
    should_update_dashboard_tile_filters_hash = False
    if not dashboard and insight.filters_hash and insight.filters_hash != cache_key:
        should_update_insight_filters_hash = True
    if dashboard:
        should_update_dashboard_tile_filters_hash = True
        if not dashboard.filters or dashboard.filters == insight.filters:
            should_update_insight_filters_hash = True
    if should_update_dashboard_tile_filters_hash:
        dashboard_tiles = DashboardTile.objects.filter(insight=insight, dashboard=dashboard,).exclude(
            filters_hash=cache_key
        )
        matching_tiles_with_no_hash = dashboard_tiles.filter(filters_hash=None).count()
        statsd.incr("update_cache_queue.set_missing_filters_hash", matching_tiles_with_no_hash)
        dashboard_tiles.update(filters_hash=cache_key)
    if should_update_insight_filters_hash:
        insight.filters_hash = cache_key
        insight.save()
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
