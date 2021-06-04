import importlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

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
    TRENDS_STICKINESS,
)
from posthog.decorators import CacheType
from posthog.ee import is_clickhouse_enabled
from posthog.models import Dashboard, DashboardItem, Filter, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.settings import CACHED_RESULTS_TTL
from posthog.types import FilterType
from posthog.utils import generate_cache_key

PARALLEL_DASHBOARD_ITEM_CACHE = int(os.environ.get("PARALLEL_DASHBOARD_ITEM_CACHE", 5))

logger = logging.getLogger(__name__)

CH_TYPE_TO_IMPORT = {
    CacheType.TRENDS: ("ee.clickhouse.queries.trends.clickhouse_trends", "ClickhouseTrends"),
    CacheType.SESSION: ("ee.clickhouse.queries.sessions.clickhouse_sessions", "ClickhouseSessions"),
    CacheType.STICKINESS: ("ee.clickhouse.queries.clickhouse_stickiness", "ClickhouseStickiness"),
    CacheType.RETENTION: ("ee.clickhouse.queries.clickhouse_retention", "ClickhouseRetention"),
    CacheType.PATHS: ("ee.clickhouse.queries.clickhouse_paths", "ClickhousePaths"),
}

TYPE_TO_IMPORT = {
    CacheType.TRENDS: ("posthog.queries.trends", "Trends"),
    CacheType.SESSION: ("posthog.queries.sessions", "Sessions"),
    CacheType.STICKINESS: ("posthog.queries.stickiness", "Stickiness"),
    CacheType.RETENTION: ("posthog.queries.retention", "Retention"),
    CacheType.PATHS: ("posthog.queries.paths", "Paths"),
}


def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> None:

    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    team_id = int(payload["team_id"])
    filter = get_filter(data=filter_dict, team=Team(pk=team_id))
    if cache_type == CacheType.FUNNEL:
        result = _calculate_funnel(filter, key, team_id)
    else:
        result = _calculate_by_filter(filter, key, team_id, cache_type)

    if result:
        cache.set(key, {"result": result, "type": cache_type, "last_refresh": timezone.now()}, CACHED_RESULTS_TTL)


def update_dashboard_items_cache(dashboard: Dashboard) -> None:
    for item in DashboardItem.objects.filter(dashboard=dashboard, filters__isnull=False).exclude(filters={}):
        cache_key, cache_type, payload = dashboard_item_update_task_params(item, dashboard)
        update_cache_item(cache_key, cache_type, payload)


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


def import_from(module: str, name: str) -> Any:
    return getattr(importlib.import_module(module), name)


def _calculate_by_filter(filter: FilterType, key: str, team_id: int, cache_type: CacheType) -> List[Dict[str, Any]]:
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)

    if is_clickhouse_enabled():
        insight_class_path = CH_TYPE_TO_IMPORT[cache_type]
    else:
        insight_class_path = TYPE_TO_IMPORT[cache_type]

    insight_class = import_from(insight_class_path[0], insight_class_path[1])
    result = insight_class().run(filter, Team(pk=team_id))
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result


def _calculate_funnel(filter: Filter, key: str, team_id: int) -> List[Dict[str, Any]]:
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)

    if is_clickhouse_enabled():
        insight_class = import_from("ee.clickhouse.queries.clickhouse_funnel", "ClickhouseFunnel")
    else:
        insight_class = import_from("posthog.queries.funnel", "Funnel")

    result = insight_class(filter=filter, team=Team(pk=team_id)).run()
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result
