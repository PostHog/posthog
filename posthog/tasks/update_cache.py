import json
import logging
from typing import Any, Dict, List, Optional, Union

from celery import group
from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.utils import timezone

from posthog.celery import update_cache_item_task
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
from posthog.models import Action, ActionStep, DashboardItem, Filter, Team
from posthog.queries.funnel import Funnel
from posthog.queries.trends import Trends
from posthog.utils import generate_cache_key

logger = logging.getLogger(__name__)


def update_cache_item(key: str, cache_type: str, payload: dict) -> None:

    result: Optional[Union[List, Dict]] = None
    filter_dict = json.loads(payload["filter"])
    filter = Filter(data=filter_dict)
    if cache_type == TRENDS_ENDPOINT:
        result = _calculate_trends(filter, int(payload["team_id"]))
    elif cache_type == FUNNEL_ENDPOINT:
        result = _calculate_funnel(filter, int(payload["team_id"]))

    if result:
        cache.set(key, {"result": result, "details": payload, "type": cache_type}, 25 * 60)


def update_cached_items() -> None:

    tasks = []
    items = (
        DashboardItem.objects.filter(
            Q(Q(dashboard__is_shared=True) | Q(dashboard__last_accessed_at__gt=timezone.now() - relativedelta(days=7)))
        )
        .exclude(dashboard__deleted=True)
        .exclude(refreshing=True)
        .exclude(deleted=True)
    )

    for item in items.filter(filters__isnull=False).exclude(filters={}).distinct("filters"):
        filter = Filter(data=item.filters)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), item.team_id))
        curr_data = cache.get(cache_key)

        # if task is logged and loading leave it alone
        if curr_data and curr_data.get("task_id", None):
            continue

        cache_type = FUNNEL_ENDPOINT if filter.insight == "FUNNELS" else TRENDS_ENDPOINT
        payload = {"filter": filter.toJSON(), "team_id": item.team_id}
        tasks.append(update_cache_item_task.s(cache_key, cache_type, payload))

    logger.info("Found {} items to refresh".format(len(tasks)))
    taskset = group(tasks)
    taskset.apply_async()


def _calculate_trends(filter: Filter, team_id: int) -> List[Dict[str, Any]]:
    actions = Action.objects.filter(team_id=team_id)
    actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters=filter.to_dict())
    dashboard_items.update(refreshing=True)
    result = Trends().run(filter, Team(pk=team_id))
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result


def _calculate_funnel(filter: Filter, team_id: int) -> List[Dict[str, Any]]:
    dashboard_items = DashboardItem.objects.filter(team_id=team_id, filters=filter.to_dict())
    dashboard_items.update(refreshing=True)
    result = Funnel(filter=filter, team=Team(pk=team_id)).run()
    dashboard_items.update(last_refresh=timezone.now(), refreshing=False)
    return result
