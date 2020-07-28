from celery import shared_task, group
from posthog.api.action import calculate_trends, get_actions
from posthog.api.funnel import FunnelSerializer
from posthog.models import Filter, Action, Funnel, Entity, DashboardItem, ActionStep
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
from posthog.utils import generate_cache_key
from posthog.celery import update_cache_item_task
from django.db.models import Prefetch, Q
from django.core.cache import cache
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import logging
from typing import List, Dict, Any, Union, Optional
import json
import datetime
from posthog.celery import app

logger = logging.getLogger(__name__)


def update_cache_item(key: str, cache_type: str, payload: dict) -> None:
    result: Optional[Union[List, Dict]] = None
    if cache_type == TRENDS_ENDPOINT:
        filter_dict = json.loads(payload["filter"])
        filter = Filter(data=filter_dict)
        result = _calculate_trends(filter, int(payload["team_id"]))
    elif cache_type == FUNNEL_ENDPOINT:
        result = _calculate_funnel(payload["funnel_id"], int(payload["team_id"]))

    if result:
        cache.set(key, {"result": result, "details": payload, "type": cache_type}, 25 * 60)


def update_cached_items() -> None:

    tasks = []
    items = (
        DashboardItem.objects.filter(
            Q(Q(dashboard__is_shared=True) | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7)))
        )
        .exclude(refreshing=True)
        .exclude(deleted=True)
    )

    for item in items.filter(filters__isnull=False).exclude(filters={}).distinct("filters"):
        filter = Filter(data=item.filters)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), item.team_id))
        payload = {"filter": filter.toJSON(), "team_id": item.team_id}
        tasks.append(update_cache_item_task.s(cache_key, TRENDS_ENDPOINT, payload))

    for item in items.filter(funnel_id__isnull=False).distinct("funnel_id"):
        cache_key = generate_cache_key("funnel_{}_{}".format(item.funnel_id, item.team_id))
        payload = {"funnel_id": item.funnel_id, "team_id": item.team_id}
        tasks.append(update_cache_item_task.s(cache_key, FUNNEL_ENDPOINT, payload))

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()


def _calculate_trends(filter: Filter, team_id: int) -> List[Dict[str, Any]]:
    actions = Action.objects.filter(team_id=team_id)
    actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters=filter.to_dict())
    dashboard_items.update(refreshing=True)
    result = calculate_trends(filter, team_id, actions)
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result


def _calculate_funnel(pk: int, team_id: int) -> dict:
    funnel = Funnel.objects.get(pk=pk, team_id=team_id)
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, funnel_id=pk)
    dashboard_items.update(refreshing=True)
    result = FunnelSerializer(funnel, context={"cache": True}).data
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result
