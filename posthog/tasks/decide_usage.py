from typing import Sequence

import structlog
from posthog.celery import app


from django.db.models import Q
from posthog.api.decide_analytics import capture_team_decide_usage
from posthog.models import Team

logger = structlog.get_logger(__name__)

MAX_AGE_MINUTES = 15


@app.task(ignore_result=True, max_retries=2)
def calculate_decide_usage() -> None:

    teams: Sequence[Team] = Team.objects.exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
    for team in teams:
        capture_team_decide_usage(team)
