from __future__ import annotations

from typing import TYPE_CHECKING

from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks

from ..adapters.identity import PostHogIdentity
from ..db import WRITER_DB
from ..facade.enums import BetsAccessLevel, IdeaOutcome, LedgerKind, ModelStep, WorkKind
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem
from .ledger import totals
from .loop import RUN_BUDGET_CENTS
from .metrics import metric
from .next_actions import next_actions
from .spend import spend_pending
from .step_models import choice, model_options, plan_available
from .workspace import get_settings, project_id

ESTIMATE_SAMPLE = 10

if TYPE_CHECKING:
    from posthog.models import Team, User

BET_FIELDS = (
    "id",
    "reference",
    "title",
    "statement",
    "audience",
    "area",
    "repository",
    "goal_insight",
    "goal_metric",
    "secondary_metrics",
    "target",
    "direction",
    "unit",
    "status",
    "note",
    "baseline_value",
    "baseline_at",
    "updated_at",
)


def can_edit(team: Team, user: User) -> bool:
    return PostHogIdentity().access_level(user, team) in (BetsAccessLevel.TRADER, BetsAccessLevel.MANAGER)


def entry(team: Team, user: User, bet: Bet) -> dict:
    ideas = list(
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, kind=WorkKind.IDEA)
        .values_list("result__outcome", flat=True)
    )
    owner = PostHogIdentity().members({bet.owner_id}).get(bet.owner_id)
    return {
        **{field: getattr(bet, field) for field in BET_FIELDS},
        "owner": {
            "user_id": bet.owner_id,
            "name": owner.name if owner else "Former member",
            "email": owner.email if owner else "",
        },
        "money": totals(bet.team_id, bet),
        "metric": metric(team, user, bet.goal_insight),
        "spend_pending": spend_pending(bet),
        "ideas_tried": sum(1 for outcome in ideas if outcome and outcome != IdeaOutcome.DROPPED),
        "ideas_won": sum(1 for outcome in ideas if outcome == IdeaOutcome.WON),
    }


def work_entry(work: WorkItem, user: User) -> dict:
    prs = (
        tasks.get_pull_requests_for_tasks(work.team_id, [work.task_id]).get(str(work.task_id), [])
        if work.task_id
        else []
    )
    native = tasks.get_task_detail(work.task_id, work.team_id, user.id) if work.task_id else None
    run = native.latest_run if native else None
    return {
        "id": work.id,
        "goal_version": work.goal_version,
        "kind": work.kind,
        "stage": work.stage,
        "title": work.title,
        "summary": work.summary,
        "note": work.note,
        "pr_url": work.pr_url or (prs[0].url if prs else ""),
        "pr_state": prs[0].state if prs else "",
        "flag_key": work.flag_key,
        "experiment_id": work.experiment_id,
        "result": work.result,
        "task_id": work.task_id if native else None,
        "task_status": run.status if run else "not_started",
        "attempts": work.attempts,
        "spent_cents": totals(work.team_id, work=work).spent_cents,
        "created_at": work.created_at,
        "finished_at": work.finished_at,
        "source": work.source,
        "assessment": work.assessment,
        "evidence": work.evidence,
        "report_id": work.report_id,
        "dismissed_reason": work.dismissed_reason,
        "moves_metric": work.moves_metric,
    }


def spend_history(bet: Bet) -> list[dict]:
    total = 0
    points = []
    for entry in (
        LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, kind=LedgerKind.SPEND)
        .order_by("created_at")
        .values("created_at", "amount_cents")
    ):
        total += entry["amount_cents"]
        points.append({"at": entry["created_at"], "spent_cents": total})
    return points


def scout_running(bet: Bet) -> bool:
    for run_id in signals.scout_run_ids_for_source(bet.team_id, "bets", [f"{bet.id}:v{bet.goal_version}"])[:5]:
        run = tasks.get_task_run(run_id, team_id=bet.team_id)
        if run and run.status in ("queued", "in_progress"):
            return True
    return False


def build_estimate_cents(team_id: int) -> int | None:
    spent: dict[str, int] = {}
    for work_id, amount in (
        LedgerEntry.objects.for_team(team_id)
        .using(WRITER_DB)
        .filter(kind=LedgerKind.SPEND, work_item__kind=WorkKind.IDEA)
        .order_by("-created_at")
        .values_list("work_item_id", "amount_cents")[:500]
    ):
        if len(spent) >= ESTIMATE_SAMPLE and str(work_id) not in spent:
            break
        spent[str(work_id)] = spent.get(str(work_id), 0) + amount
    return round(sum(spent.values()) / len(spent)) if spent else None


def detail(team: Team, user: User, bet: Bet) -> dict:
    scout = next(
        (item for item in signals.scouts_for_source(bet.team_id, "bets", f"{bet.id}:v{bet.goal_version}")),
        None,
    )
    actions = sorted(next_actions(bet), key=lambda item: item["priority"])
    return {
        **entry(team, user, bet),
        "goal_version": bet.goal_version,
        "build_estimate_cents": build_estimate_cents(bet.team_id),
        "build_cap_cents": RUN_BUDGET_CENTS,
        "goal_met_since": bet.goal_met_since,
        "work": [
            work_entry(work, user)
            for work in WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet).order_by("-created_at")
        ],
        "spend_history": spend_history(bet),
        "is_owner": user.id == bet.owner_id,
        "secondary_values": [metric(team, user, item["insight"]) for item in bet.secondary_metrics],
        "scout": {
            "config_id": scout.config_id,
            "name": scout.skill_name,
            "enabled": scout.enabled,
            "running": scout_running(bet),
        }
        if scout
        else None,
        "next_action": actions[0] if actions else None,
        "can_edit": can_edit(team, user),
    }


def overview(team: Team, user: User) -> dict:
    team_id = project_id(team)
    settings = get_settings(team_id)
    allocated = totals(team_id).allocated_cents
    bets = list(Bet.objects.for_team(team_id).using(WRITER_DB).order_by("-created_at")[:200])
    return {
        "bets": [entry(team, user, bet) for bet in bets],
        "next_actions": sorted([item for bet in bets for item in next_actions(bet)], key=lambda item: item["priority"]),
        "north_star": metric(team, user, settings.north_star_insight),
        "settings": settings_entry(settings, user),
        "allocated_cents": allocated,
        "unallocated_cents": settings.budget_cents - allocated,
        "can_edit": can_edit(team, user),
    }


def settings_entry(settings: BetsSettings, user: User) -> dict:
    return {
        "budget_cents": settings.budget_cents,
        "north_star_insight": settings.north_star_insight,
        "min_run_hours": settings.min_run_hours,
        "goal_confirm_hours": settings.goal_confirm_hours,
        "models": [choice(settings, user, step) for step in ModelStep],
        "model_options": model_options(),
        "plan_available": plan_available(user),
    }
