from django.db.models import QuerySet

from ..db import WRITER_DB
from ..facade.enums import BetStatus, WorkStage
from ..models import Bet, WorkItem

ACTIVE = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)
OPEN = (*ACTIVE, WorkStage.STUCK)
LIVE = (BetStatus.SETTING_UP, BetStatus.RUNNING)
ENDED = (BetStatus.REACHED, BetStatus.SPENT, BetStatus.CLOSED)


def items(bet: Bet) -> QuerySet[WorkItem]:
    return WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet, goal_version=bet.goal_version)


def source_id(bet: Bet) -> str:
    return f"{bet.id}:v{bet.goal_version}"
