from celery import shared_task
from posthog.api.action import calculate_trends, get_actions
from posthog.api.funnel import FunnelSerializer
from posthog.models import Team, Filter, Action, Funnel
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
import logging
from typing import List, Dict, Any, Union, Optional

logger = logging.getLogger(__name__)

@shared_task
def update_cache(cache_type: str, payload: dict) -> Optional[Union[dict, List[Dict[str, Any]]]]:
    if cache_type == TRENDS_ENDPOINT:
        return _calculate_trends(payload['filter'], payload['params'], payload['team'])
    elif cache_type == FUNNEL_ENDPOINT:
        return _calculate_funnels(payload['pk'], payload['params'], payload['team'])
    return None

def _calculate_trends(filter: Filter, params: dict, team: Team) -> List[Dict[str, Any]]:
    actions = get_actions(Action.objects.all(), params, team)
    data = calculate_trends(filter, params, team, actions)
    return data

def _calculate_funnels(pk: str, params: dict, team: Team) -> dict:
    funnel = Funnel.objects.filter(pk=pk, team=team)
    return FunnelSerializer(funnel).data

