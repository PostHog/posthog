from celery import shared_task
from posthog.api.action import calculate_trends, get_actions
from posthog.api.funnel import FunnelSerializer
from posthog.models import Filter, Action, Funnel, Entity
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
import logging
from typing import List, Dict, Any, Union, Optional
import json

logger = logging.getLogger(__name__)

@shared_task
def update_cache(cache_type: str, payload: dict) -> Optional[Union[dict, List[Dict[str, Any]]]]:
    if cache_type == TRENDS_ENDPOINT:
        filter_dict = json.loads(payload['filter'])
        entities = [Entity(entity_dict) for entity_dict in filter_dict.get('entities', [])]
        filter_dict.update({'entities': entities})
        filter = Filter(data=filter_dict)
        return _calculate_trends(filter, payload['params'], payload['team_id'])
        
    elif cache_type == FUNNEL_ENDPOINT:
        return _calculate_funnels(payload['pk'], payload['params'], payload['team_id'])
    return None

def _calculate_trends(filter: Filter, params: dict, team_id: str) -> List[Dict[str, Any]]:
    actions = get_actions(Action.objects.all(), params, team_id)
    actions = actions.filter(deleted=False)
    data = calculate_trends(filter, params, team_id, actions)
    return data

def _calculate_funnels(pk: str, params: dict, team_id: str) -> dict:
    funnel = Funnel.objects.get(pk=pk, team_id=team_id)
    return FunnelSerializer(funnel, context={'cache': True}).data

