import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import structlog
from celery import group
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.expressions import F
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
from posthog.models import Dashboard, Filter, Insight, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.types import FilterType
from posthog.utils import generate_cache_key

PARALLEL_INSIGHT_CACHE = int(os.environ.get("PARALLEL_DASHBOARD_ITEM_CACHE", 5))

logger = structlog.get_logger(__name__)

from ee.clickhouse.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from ee.clickhouse.queries.funnels.utils import get_funnel_order_class
from ee.clickhouse.queries.paths import ClickhousePaths
from ee.clickhouse.queries.retention.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends

CACHE_TYPE_TO_INSIGHT_CLASS = {
    CacheType.TRENDS: ClickhouseTrends,
    CacheType.STICKINESS: ClickhouseStickiness,
    CacheType.RETENTION: ClickhouseRetention,
    CacheType.PATHS: ClickhousePaths,
}


def update_cache_item(key: str, cache_type: CacheType, payload: dict) -> List[Dict[str, Any]]:
    timer = statsd.timer("update_cache_item_timer").start()
    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    team_id = int(payload["team_id"])
    filter = get_filter(data=filter_dict, team=Team(pk=team_id))

    # Doing the filtering like this means we'll update _all_ Insights with the same filters hash
    dashboard_items = Insight.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)

    try:
        if cache_type == CacheType.FUNNEL:
            result = _calculate_funnel(filter, key, team_id)
        else:
            result = _calculate_by_filter(filter, key, team_id, cache_type)
        cache.set(
            key, {"result": result, "type": cache_type, "last_refresh": timezone.now()}, settings.CACHED_RESULTS_TTL
        )
    except Exception as e:
        timer.stop()
        statsd.incr("update_cache_item_error")
        dashboard_items.filter(refresh_attempt=None).update(refresh_attempt=0)
        dashboard_items.update(refreshing=False, refresh_attempt=F("refresh_attempt") + 1)
        raise e

    timer.stop()
    statsd.incr("update_cache_item_success")
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
    return result


def update_dashboard_item_cache(dashboard_item: Insight, dashboard: Optional[Dashboard]) -> List[Dict[str, Any]]:
    cache_key, cache_type, payload = dashboard_item_update_task_params(dashboard_item, dashboard)
    result = update_cache_item(cache_key, cache_type, payload)
    dashboard_item.refresh_from_db()
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


def update_cached_items() -> None:

    tasks = []
    items = (
        Insight.objects.filter(
            Q(Q(dashboard__is_shared=True) | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7)))
        )
        .exclude(dashboard__deleted=True)
        .exclude(refreshing=True)
        .exclude(deleted=True)
        .exclude(refresh_attempt__gt=2)
        .exclude(filters={})
        .order_by(F("last_refresh").asc(nulls_first=True))
    )

    for item in items[0:PARALLEL_INSIGHT_CACHE]:
        try:
            cache_key, cache_type, payload = dashboard_item_update_task_params(item)
            if item.filters_hash != cache_key:
                item.save()  # force update if the saved key is different from the cache key
            tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))
        except Exception as e:
            item.refresh_attempt = (item.refresh_attempt or 0) + 1
            item.save()
            capture_exception(e)

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()
    statsd.gauge("update_cache_queue_depth", items.count())


def dashboard_item_update_task_params(
    item: Insight, dashboard: Optional[Dashboard] = None
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

    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        result = ClickhouseFunnelTrends(team=team, filter=filter).run()
    elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
        result = ClickhouseFunnelTimeToConvert(team=team, filter=filter).run()
    else:
        funnel_order_class = get_funnel_order_class(filter)
        result = funnel_order_class(team=team, filter=filter).run()

    return result
