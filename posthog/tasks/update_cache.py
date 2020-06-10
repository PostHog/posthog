from celery import shared_task
from posthog.api.action import calculate_trends, get_actions
from posthog.api.funnel import FunnelSerializer
from posthog.models import Team, Filter, Action, Funnel
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT
import logging

logger = logging.getLogger(__name__)

@shared_task
def update_cache(cache_type: str, payload: dict):
    if cache_type == TRENDS_ENDPOINT:
        return _calculate_trends(payload['filter'], payload['params'], payload['team'])
    elif cache_type == FUNNEL_ENDPOINT:
        return _calculate_funnels(payload['pk'], payload['params'], payload['team'])

def _calculate_trends(filter: Filter, params: dict, team: Team):
    actions = get_actions(Action.objects.all(), params, team)
    data = calculate_trends(filter, params, team, actions)
    return data

def _calculate_funnels(pk: str, params: dict, team: Team):
    funnel = Funnel.objects.filter(pk=pk, team=team)
    return FunnelSerializer(funnel).data

