from celery import shared_task
from posthog.api.action import calculate_trends, get_actions
from posthog.api.funnel import FunnelSerializer
from posthog.models import Filter, Action, Funnel, Entity, DashboardItem
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
import logging
from typing import List, Dict, Any, Union, Optional
import json
import datetime

logger = logging.getLogger(__name__)


@shared_task
def update_cache(
    cache_type: str, payload: dict
) -> Optional[Union[dict, List[Dict[str, Any]]]]:
    result: Optional[Union[dict, List[Dict[str, Any]]]] = None

    if cache_type == TRENDS_ENDPOINT:

        # convert filter
        filter_dict = json.loads(payload["filter"])
        filter = Filter(data=filter_dict)

        result = _calculate_trends(filter, payload["params"], int(payload["team_id"]))

    elif cache_type == FUNNEL_ENDPOINT:
        result = _calculate_funnels(
            payload["pk"], payload["params"], int(payload["team_id"])
        )

    dashboard_items = DashboardItem.objects.filter(
        team_id=payload["team_id"], filters=Filter(data=filter_dict).to_dict()
    )
    dashboard_items.update(last_refresh=datetime.datetime.now(), refreshing=False)

    return result


def _calculate_trends(
    filter: Filter, params: dict, team_id: int
) -> List[Dict[str, Any]]:
    actions = get_actions(Action.objects.all(), params, team_id)
    data = calculate_trends(filter, params, team_id, actions)
    return data


def _calculate_funnels(pk: str, params: dict, team_id: int) -> dict:
    funnel = Funnel.objects.get(pk=pk, team_id=team_id)
    return FunnelSerializer(funnel, context={"cache": True}).data
