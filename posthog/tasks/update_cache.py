import importlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from celery import group
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.expressions import F, Subquery
from django.utils import timezone

from posthog.celery import update_cache_item_task
from posthog.constants import FUNNELS, PATHS, RETENTION, STICKINESS, TRENDS
from posthog.decorators import TYPE_TO_FILTER, CacheType
from posthog.ee import is_ee_enabled
from posthog.models import DashboardItem, Filter, Team
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.funnel import Funnel
from posthog.settings import CACHED_RESULTS_TTL
from posthog.utils import generate_cache_key

PARALLEL_DASHBOARD_ITEM_CACHE = int(os.environ.get("PARALLEL_DASHBOARD_ITEM_CACHE", 5))

logger = logging.getLogger(__name__)

CH_TYPE_TO_IMPORT = {
    CacheType.TRENDS: ("ee.clickhouse.queries.trends.clickhouse_trends", "ClickhouseTrends"),
    CacheType.STICKINESS: ("ee.clickhouse.queries.clickhouse_stickiness", "ClickhouseStickiness"),
    CacheType.RETENTION: ("ee.clickhouse.queries.clickhouse_retention", "ClickhouseRetention"),
    CacheType.PATHS: ("ee.clickhouse.queries.trends.clickhouse_paths", "ClickhousePaths"),
}

TYPE_TO_IMPORT = {
    CacheType.TRENDS: ("posthog.queries.trends", "Trends"),
    CacheType.STICKINESS: ("posthog.queries.stickiness", "Stickiness"),
    CacheType.RETENTION: ("posthog.queries.retention", "Retention"),
    CacheType.PATHS: ("posthog.queries.paths", "Paths"),
}


def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> None:
    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    filter = Filter(data=filter_dict)
    if cache_type == CacheType.FUNNEL:
        result = _calculate_funnel(filter, key, int(payload["team_id"]))
    else:
        team = Team(pk=int(payload["team_id"]))
        filter = TYPE_TO_FILTER[cache_type](data=filter_dict, team=team)
        result = _calculate_by_filter(filter, key, int(payload["team_id"]), cache_type)

    if result is not None:
        cache.set(key, {"result": result, "details": payload, "type": cache_type}, CACHED_RESULTS_TTL)


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
        filter = Filter(data=item.filters)
        cache_type = get_cache_type(filter)
        team = Team(pk=item.team_id)

        new_filter = TYPE_TO_FILTER[cache_type](data=item.filters, team=team)
        cache_key = generate_cache_key("{}_{}".format(new_filter.toJSON(), item.team_id))

        payload = {"filter": new_filter.toJSON(), "team_id": item.team_id}
        tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()


def get_cache_type(filter: Filter) -> CacheType:
    if filter.insight == FUNNELS:
        return CacheType.FUNNEL
    elif filter.insight == PATHS:
        return CacheType.PATHS
    elif filter.insight == RETENTION:
        return CacheType.RETENTION
    elif filter.insight == TRENDS and filter.shown_as == STICKINESS:
        return CacheType.STICKINESS
    else:
        return CacheType.TRENDS


def import_from(module: str, name: str) -> Any:
    return getattr(importlib.import_module(module), name)


def _calculate_by_filter(
    filter: Union[Filter, RetentionFilter, StickinessFilter], key: str, team_id: int, cache_type: CacheType
) -> List[Dict[str, Any]]:
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)

    if is_ee_enabled() and settings.EE_AVAILABLE:
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
    result = Funnel(filter=filter, team=Team(pk=team_id)).run()
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result
