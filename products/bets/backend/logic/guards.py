from ..db import WRITER_DB
from ..facade.enums import WorkStage
from ..models import WorkItem
from .ledger import totals
from .stages import LIVE


def task_start_refusal(task_id: str, team_id: int) -> str | None:
    work = WorkItem.objects.for_team(team_id).using(WRITER_DB).select_related("bet").filter(task_id=task_id).first()
    if work is None:
        return "This task is not linked to current bet work."
    bet = work.bet
    if bet.status not in LIVE:
        return "The bet is not running."
    if work.goal_version != bet.goal_version or work.stage in (WorkStage.DONE, WorkStage.DROPPED):
        return "This work is finished."
    if totals(team_id, work=work).reserved_cents <= 0 and totals(team_id, bet).available_cents <= 0:
        return "The bet has no budget left."
    return None
