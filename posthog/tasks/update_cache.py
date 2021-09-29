import importlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from celery import group
from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.db.models.expressions import F, Subquery
from django.utils import timezone

from posthog.celery import update_cache_item_task
from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_RETENTION,
    INSIGHT_SESSIONS,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    TRENDS_LINEAR,
    TRENDS_STICKINESS,
    FunnelOrderType,
    FunnelVizType,
)
from posthog.decorators import CacheType
from posthog.models import Dashboard, DashboardItem, Filter, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.settings import CACHED_RESULTS_TTL
from posthog.types import FilterType
from posthog.utils import generate_cache_key, is_clickhouse_enabled

PARALLEL_DASHBOARD_ITEM_CACHE = int(os.environ.get("PARALLEL_DASHBOARD_ITEM_CACHE", 5))

logger = logging.getLogger(__name__)

if is_clickhouse_enabled():
    from ee.clickhouse.queries import ClickhousePaths
    from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
    from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
    from ee.clickhouse.queries.funnels import (
        ClickhouseFunnel,
        ClickhouseFunnelBase,
        ClickhouseFunnelStrict,
        ClickhouseFunnelTimeToConvert,
        ClickhouseFunnelTrends,
        ClickhouseFunnelUnordered,
    )
    from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
    from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends

    CACHE_TYPE_TO_INSIGHT_CLASS = {
        CacheType.TRENDS: ClickhouseTrends,
        CacheType.SESSION: ClickhouseSessions,
        CacheType.STICKINESS: ClickhouseStickiness,
        CacheType.RETENTION: ClickhouseRetention,
        CacheType.PATHS: ClickhousePaths,
    }
else:
    from posthog.queries.funnel import Funnel
    from posthog.queries.paths import Paths
    from posthog.queries.retention import Retention
    from posthog.queries.sessions.sessions import Sessions
    from posthog.queries.stickiness import Stickiness
    from posthog.queries.trends import Trends

    CACHE_TYPE_TO_INSIGHT_CLASS = {
        CacheType.TRENDS: Trends,
        CacheType.SESSION: Sessions,
        CacheType.STICKINESS: Stickiness,
        CacheType.RETENTION: Retention,
        CacheType.PATHS: Paths,
    }


def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> None:
    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    team_id = int(payload["team_id"])
    filter = get_filter(data=filter_dict, team=Team(pk=team_id))

    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)

    if cache_type == CacheType.FUNNEL:
        result = _calculate_funnel(filter, key, team_id)
    else:
        result = _calculate_by_filter(filter, key, team_id, cache_type)
    cache.set(key, {"result": result, "type": cache_type, "last_refresh": timezone.now()}, CACHED_RESULTS_TTL)

    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)


def update_dashboard_items_cache(dashboard: Dashboard) -> None:
    for item in DashboardItem.objects.filter(dashboard=dashboard, filters__isnull=False).exclude(filters={}):
        update_dashboard_item_cache(item, dashboard)


def update_dashboard_item_cache(dashboard_item: DashboardItem, dashboard: Optional[Dashboard]) -> None:
    cache_key, cache_type, payload = dashboard_item_update_task_params(dashboard_item, dashboard)
    update_cache_item(cache_key, cache_type, payload)
    dashboard_item.refresh_from_db()


def get_cache_type(filter: FilterType) -> CacheType:
    if filter.insight == INSIGHT_FUNNELS:
        return CacheType.FUNNEL
    elif filter.insight == INSIGHT_SESSIONS:
        return CacheType.SESSION
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


def update_cached_items() -> None:

    tasks = []
    items = (
        DashboardItem.objects.filter(
            Q(Q(dashboard__is_shared=True) | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7)))
        )
        .exclude(dashboard__deleted=True)
        .exclude(refreshing=True)
        .exclude(deleted=True)
        .distinct("filters_hash")
    )

    for item in DashboardItem.objects.filter(
        pk__in=Subquery(items.filter(filters__isnull=False).exclude(filters={}).distinct("filters").values("pk"))
    ).order_by(F("last_refresh").asc(nulls_first=True))[0:PARALLEL_DASHBOARD_ITEM_CACHE]:
        cache_key, cache_type, payload = dashboard_item_update_task_params(item)
        tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()


def dashboard_item_update_task_params(
    item: DashboardItem, dashboard: Optional[Dashboard] = None
) -> Tuple[str, CacheType, Dict]:
    filter = get_filter(data=item.dashboard_filters(dashboard), team=item.team)
    cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), item.team_id))

    cache_type = get_cache_type(filter)
    payload = {"filter": filter.toJSON(), "team_id": item.team_id}

    return cache_key, cache_type, payload


def _calculate_by_filter(filter: FilterType, key: str, team_id: int, cache_type: CacheType) -> List[Dict[str, Any]]:
    insight_class = CACHE_TYPE_TO_INSIGHT_CLASS[cache_type]

    if cache_type == CacheType.PATHS:
        result = insight_class(filter, Team(pk=team_id)).run(filter, Team(pk=team_id))
    else:
        result = insight_class().run(filter, Team(pk=team_id))
    return result


def _calculate_funnel(filter: Filter, key: str, team_id: int) -> List[Dict[str, Any]]:
    team = Team(pk=team_id)

    if is_clickhouse_enabled():
        funnel_order_class: Type[ClickhouseFunnelBase] = ClickhouseFunnel
        if filter.funnel_order_type == FunnelOrderType.UNORDERED:
            funnel_order_class = ClickhouseFunnelUnordered
        elif filter.funnel_order_type == FunnelOrderType.STRICT:
            funnel_order_class = ClickhouseFunnelStrict

        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            result = ClickhouseFunnelTrends(team=team, filter=filter, funnel_order_class=funnel_order_class).run()
        elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
            result = ClickhouseFunnelTimeToConvert(
                team=team, filter=filter, funnel_order_class=funnel_order_class
            ).run()
        else:
            result = funnel_order_class(team=team, filter=filter).run()
    else:
        result = Funnel(filter=filter, team=team).run()

    return result
