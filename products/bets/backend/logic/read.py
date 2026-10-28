from __future__ import annotations

import math
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from django.db.models import Sum

from posthog.models import Team

from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks

from ..adapters.identity import Member, PostHogIdentity
from ..db import WRITER_DB
from ..facade.contracts import Metric
from ..facade.enums import BetsAccessLevel, BetStatus, IdeaOutcome, LedgerKind, ModelStep, WorkKind, WorkStage
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem
from .ledger import totals
from .metrics import metric, proposed_plan
from .next_actions import NextAction, next_actions
from .scout import recent_scout_runs
from .step_models import choice, model_options, plan_available
from .workspace import get_settings, project_id

if TYPE_CHECKING:
    from posthog.models import User

BET_FIELDS = (
    "id",
    "reference",
    "title",
    "statement",
    "audience",
    "area",
    "repository",
    "goal_insight",
    "goal_description",
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


PLAN_DEFAULTS = {
    "days": None,
    "mde": None,
    "audience": None,
    "weekly": False,
    "too_long": False,
    "mean": None,
    "variance": None,
    "proposed_days": None,
    "approved": False,
    "replanned": False,
}


def can_edit(team: Team, user: User) -> bool:
    return PostHogIdentity().access_level(user, team) in (BetsAccessLevel.TRADER, BetsAccessLevel.MANAGER)


def goal_metric(team: Team, user: User, bet: Bet) -> Metric:
    if not bet.goal_insight and bet.goal_description:
        return replace(metric(team, user, ""), message="Bets is finding the insight for this measure.")
    return metric(team, user, bet.goal_insight)


def entry(
    team: Team,
    user: User,
    bet: Bet,
    *,
    actions: list[NextAction] | None = None,
    owners: dict[int, Member] | None = None,
) -> dict:
    ideas = list(
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, kind=WorkKind.IDEA)
        .values_list("result__outcome", flat=True)
    )
    owner = (owners if owners is not None else PostHogIdentity().members({bet.owner_id})).get(bet.owner_id)
    money = totals(bet.team_id, bet)
    actions = next_actions(bet) if actions is None else actions
    return {
        **{field: getattr(bet, field) for field in BET_FIELDS},
        "repositories": bet.repos,
        "owner": {
            "user_id": bet.owner_id,
            "name": owner.name if owner else "Former member",
            "email": owner.email if owner else "",
        },
        "money": money,
        "metric": goal_metric(team, user, bet),
        "spend_pending": money.reserved_cents > 0,
        "ideas_tried": sum(1 for outcome in ideas if outcome and outcome != IdeaOutcome.DROPPED),
        "ideas_won": sum(1 for outcome in ideas if outcome == IdeaOutcome.WON),
        "needs_you": bet.status in (BetStatus.SETTING_UP, BetStatus.RUNNING) and bool(actions),
    }


def work_entry(
    work: WorkItem, user: User, pull_requests: dict, spent: dict[str, int], plan: dict | None = None
) -> dict:
    prs = pull_requests.get(str(work.task_id), []) if work.task_id else []
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
        "spent_cents": spent.get(str(work.id), 0),
        "created_at": work.created_at,
        "finished_at": work.finished_at,
        "source": work.source,
        "assessment": work.assessment,
        "evidence": work.evidence,
        "report_id": work.report_id,
        "dismissed_reason": work.dismissed_reason,
        "moves_metric": work.moves_metric,
        "plan": {**PLAN_DEFAULTS, **(plan if plan is not None else work.plan)},
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
    return any(run.status in ("queued", "in_progress") for run in recent_scout_runs(bet))


def work_entries(bet: Bet, user: User) -> list[dict]:
    items = list(WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet).order_by("-created_at"))
    task_ids = [work.task_id for work in items if work.task_id]
    pull_requests = tasks.get_pull_requests_for_tasks(bet.team_id, task_ids) if task_ids else {}
    spent = {
        str(work_id): total
        for work_id, total in LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, kind=LedgerKind.SPEND, work_item__isnull=False)
        .values("work_item_id")
        .annotate(total=Sum("amount_cents"))
        .values_list("work_item_id", "total")
    }
    proposals = idea_proposals(bet, user, [work for work in items if work.stage == WorkStage.PROPOSED])
    return [work_entry(work, user, pull_requests, spent, proposals.get(work.id)) for work in items]


def idea_proposals(bet: Bet, user: User, ideas: list[WorkItem]) -> dict:
    if not ideas or not bet.goal_insight:
        return {}
    team = Team.objects.get(id=bet.team_id)
    settings = get_settings(bet.team_id)
    proposals = {}
    for work in ideas:
        proposal = proposed_plan(
            team,
            user,
            bet.goal_insight,
            audience=work.plan.get("audience"),
            mde=settings.mde_percent,
            floor_days=math.ceil(settings.min_run_hours / 24),
        )
        if proposal:
            planned, spread = proposal
            proposals[work.id] = {
                **(asdict(planned) if planned else {"mde": settings.mde_percent}),
                "mean": spread.mean,
                "variance": spread.variance,
            }
    return proposals


def detail(team: Team, user: User, bet: Bet) -> dict:
    scout = next(
        (item for item in signals.scouts_for_source(bet.team_id, "bets", f"{bet.id}:v{bet.goal_version}")),
        None,
    )
    actions = sorted(next_actions(bet), key=lambda item: item["priority"])
    return {
        **entry(team, user, bet),
        "goal_version": bet.goal_version,
        "goal_met_since": bet.goal_met_since,
        "work": work_entries(bet, user),
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
    actions = {bet.id: next_actions(bet) for bet in bets}
    owners = PostHogIdentity().members({bet.owner_id for bet in bets})
    return {
        "bets": [entry(team, user, bet, actions=actions[bet.id], owners=owners) for bet in bets],
        "next_actions": sorted([item for bet in bets for item in actions[bet.id]], key=lambda item: item["priority"]),
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
        "mde_percent": settings.mde_percent,
        "goal_confirm_hours": settings.goal_confirm_hours,
        "models": [choice(settings, user, step) for step in ModelStep],
        "model_options": model_options(),
        "plan_available": plan_available(user),
    }
