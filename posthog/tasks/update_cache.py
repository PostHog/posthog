import json
import logging
from typing import Any, Dict, List, Optional, Union

from celery import group
from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.utils import timezone

from posthog.celery import update_cache_item_task
from posthog.decorators import CacheType
from posthog.models import Action, ActionStep, DashboardItem, Filter, Team
from posthog.models.filters.filter import get_filter
from posthog.queries.funnel import Funnel
from posthog.queries.trends import Trends
from posthog.settings import CACHED_RESULTS_TTL
from posthog.utils import generate_cache_key

logger = logging.getLogger(__name__)


def update_cache_item(key: str, cache_type: str, payload: dict) -> None:

    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    filter = get_filter(data=filter_dict, team=Team(pk=payload["team_id"]))
    if cache_type == CacheType.TRENDS:
        result = _calculate_trends(filter, key, int(payload["team_id"]))
    elif cache_type == CacheType.FUNNEL:
        result = _calculate_funnel(filter, key, int(payload["team_id"]))

    if result:
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

    for item in items.filter(filters__isnull=False).exclude(filters={}).distinct("filters"):
        filter = get_filter(data=item.filters, team=item.team)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), item.team_id))
        curr_data = cache.get(cache_key)

        cache_type = CacheType.FUNNEL if filter.insight == "FUNNELS" else CacheType.TRENDS
        payload = {"filter": filter.toJSON(), "team_id": item.team_id}
        tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()


def _calculate_trends(filter: Filter, key: str, team_id: int) -> List[Dict[str, Any]]:
    actions = Action.objects.filter(team_id=team_id)
    actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)
    result = Trends().run(filter, Team(pk=team_id))
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result


def _calculate_funnel(filter: Filter, key: str, team_id: int) -> List[Dict[str, Any]]:
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters_hash=key)
    dashboard_items.update(refreshing=True)
    result = Funnel(filter=filter, team=Team(pk=team_id)).run()
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result
