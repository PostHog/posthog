from celery import shared_task
from posthog.api.action import ActionViewSet
from posthog.models import Team, Filter
from rest_framework import request
import logging

logger = logging.getLogger(__name__)

@shared_task
def calculate_trends(filter: Filter, params: dict, team: Team) -> None:
    data = ActionViewSet(action='list').calculate_trends(filter, params, team)
    return data

