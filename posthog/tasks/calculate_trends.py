from celery import shared_task
from posthog.api.action import calculate_trends, get_actions
from posthog.models import Team, Filter, Action
import logging

logger = logging.getLogger(__name__)

@shared_task
def calculate_trends_task(filter: Filter, params: dict, team: Team):
    actions = get_actions(Action.objects.all(), params, team)
    data = calculate_trends(filter, params, team, actions)
    return data

