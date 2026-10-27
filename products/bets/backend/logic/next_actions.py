from typing import TypedDict

from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import BetStatus, WorkKind, WorkStage
from ..models import Bet, WorkItem
from .ledger import totals
from .plan import EXPOSURE_GRACE


class NextAction(TypedDict):
    id: str
    bet_id: str
    bet_title: str
    title: str
    description: str
    label: str
    work_id: str | None
    url: str
    priority: int


def action(
    bet: Bet,
    key: str,
    title: str,
    description: str,
    label: str,
    priority: int,
    work: WorkItem | None = None,
    url: str = "",
) -> NextAction:
    return NextAction(
        id=f"{bet.id}:{key}",
        bet_id=str(bet.id),
        bet_title=bet.title,
        title=title,
        description=description,
        label=label,
        work_id=str(work.id) if work else None,
        url=url,
        priority=priority,
    )


def unseen(work: WorkItem) -> bool:
    if work.merged_at is None or work.plan.get("exposed_at"):
        return False
    return timezone.now() - work.merged_at > EXPOSURE_GRACE


def next_actions(bet: Bet) -> list[NextAction]:
    if bet.status == BetStatus.REACHED:
        return [
            action(
                bet,
                "reached",
                "The goal is reached",
                "Close the bet, or raise the target to keep going.",
                "Goal reached",
                0,
            )
        ]
    if bet.status == BetStatus.SPENT:
        return [
            action(
                bet,
                "spent",
                "The budget is used",
                "Add budget to continue, or close the bet.",
                "Budget used",
                0,
            )
        ]
    if bet.status not in (BetStatus.SETTING_UP, BetStatus.RUNNING):
        return []
    result: list[NextAction] = []
    proposed = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, stage=WorkStage.PROPOSED)
    )
    building = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(
            bet=bet,
            goal_version=bet.goal_version,
            kind=WorkKind.IDEA,
            stage__in=[WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE],
        )
    )
    if (count := proposed.count()) and not building.exists():
        result.append(
            action(
                bet,
                "choose",
                "Choose an idea to build",
                f"{count} {'idea is' if count == 1 else 'ideas are'} ready. Nothing is built until you choose one.",
                "Choose an idea",
                0,
            )
        )
    for work in (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, stage__in=[WorkStage.REVIEW, WorkStage.STUCK, WorkStage.LIVE])
    ):
        if work.stage == WorkStage.LIVE:
            if work.plan.get("proposed_days"):
                result.append(action(bet, f"{work.id}:extend", work.title, work.note, "Extend or stop", 0, work))
            elif unseen(work):
                result.append(
                    action(bet, f"{work.id}:unseen", work.title, work.note, "Check the deploy", 0, work, work.pr_url)
                )
        elif work.stage == WorkStage.REVIEW:
            result.append(
                action(
                    bet,
                    f"{work.id}:review",
                    work.title,
                    "Review and merge the pull request when you are happy with it.",
                    "Pull request",
                    1,
                    work,
                    work.pr_url,
                )
            )
        else:
            result.append(action(bet, f"{work.id}:stuck", work.title, work.note, "Needs attention", 0, work))
    if bet.status == BetStatus.RUNNING and totals(bet.team_id, bet).available_cents <= 0:
        result.append(
            action(bet, "budget", "The budget is used up", "Add budget to keep going, or close the bet.", "Budget", 0)
        )
    return result
