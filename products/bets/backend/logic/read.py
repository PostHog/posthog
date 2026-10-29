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
from ..facade.enums import BetsAccessLevel, IdeaOutcome, LedgerKind, ModelStep, WorkKind, WorkStage
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem
from .ledger import totals
from .metrics import metric, proposed_plan
from .scout import recent_scout_runs
from .state import bet_state, meets, tested
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
    "baseline_value",
    "baseline_at",
    "updated_at",
)


ENDED = ("reached", "spent", "closed")
WEAK_SAMPLE = 100
RETURN_KEYS = ("return:", "close:")


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
    return metric(team, user, bet.goal_insight, complete=True)


def entry(
    team: Team,
    user: User,
    bet: Bet,
    *,
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
    measured = goal_metric(team, user, bet)
    state = bet_state(bet, measured.current)
    return {
        **{field: getattr(bet, field) for field in BET_FIELDS},
        "repositories": bet.repos,
        "owner": {
            "user_id": bet.owner_id,
            "name": owner.name if owner else "Former member",
            "email": owner.email if owner else "",
        },
        "money": money,
        "metric": measured,
        "spend_pending": money.reserved_cents > 0,
        "ideas_tried": sum(1 for outcome in ideas if tested(outcome)),
        "ideas_won": sum(1 for outcome in ideas if outcome == IdeaOutcome.WON),
        "needs_you": state.needs_you,
        "state": state,
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
        "number": build_number(work),
        "chosen_at": work.chosen_at,
        "merged_at": work.merged_at,
        "exposed_at": work.plan.get("exposed_at"),
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


def build_number(work: WorkItem) -> int | None:
    suffix = work.flag_key.rpartition("-")[2]
    return int(suffix) if work.flag_key and suffix.isdecimal() else None


def effect(work: WorkItem) -> list[float] | None:
    primary = work.result.get("primary") or {}
    chosen = primary.get(work.result.get("variant") or "")
    found = chosen or next((value for value in primary.values() if value), None)
    return [float(found[0]), float(found[1])] if found and len(found) == 2 else None


def people(work: WorkItem) -> int | None:
    exposures = work.result.get("exposures") or {}
    counted = [value for key, value in exposures.items() if not key.startswith("$")]
    return int(sum(counted)) if counted else None


def learning(work: WorkItem) -> str:
    outcome = work.result.get("outcome")
    if outcome == IdeaOutcome.HARMED:
        harmed = ", ".join(work.result.get("harmed_guardrails") or []) or "A guardrail"
        return f"{harmed} got worse with the change. Fix that before you test it again."
    if outcome == IdeaOutcome.BROKEN:
        return "The test was broken, so it says nothing about the idea yet."
    return ""


def weak_evidence(work: WorkItem) -> bool:
    outcome = work.result.get("outcome")
    smallest = work.result.get("smallest_sample")
    return outcome in (IdeaOutcome.WON, IdeaOutcome.LOST, IdeaOutcome.FLAT) and (smallest or 0) < WEAK_SAMPLE


def idea_result(work: WorkItem, spent: dict[str, int]) -> dict:
    return {
        "id": work.id,
        "number": build_number(work),
        "title": work.title,
        "outcome": work.result.get("outcome") or IdeaOutcome.DROPPED,
        "effect": effect(work),
        "people": people(work),
        "spent_cents": spent.get(str(work.id), 0),
        "shipped": work.result.get("shipped"),
        "pr_url": work.pr_url,
        "finished_at": work.finished_at,
        "harmed_guardrails": work.result.get("harmed_guardrails") or [],
        "dismissed_reason": work.dismissed_reason,
        "learning": learning(work),
        "weak_evidence": weak_evidence(work),
    }


def spend_split(bet: Bet, tested_count: int) -> dict:
    rows = LedgerEntry.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet)
    spent = list(rows.filter(kind=LedgerKind.SPEND).values("amount_cents", "source_ref", "work_item__kind"))
    by_kind = {kind: sum(row["amount_cents"] for row in spent if row["work_item__kind"] == kind) for kind in WorkKind}
    scout = [row for row in spent if row["work_item__kind"] is None]
    returned = sum(
        row.amount_cents for row in rows.filter(kind=LedgerKind.DEALLOCATE) if row.key.startswith(RETURN_KEYS)
    )
    total = sum(row["amount_cents"] for row in spent)
    return {
        "scout_cents": sum(row["amount_cents"] for row in scout),
        "scout_runs": len({row["source_ref"].split(":")[1] for row in scout if row["source_ref"].count(":") >= 1}),
        "ideas_cents": by_kind[WorkKind.IDEA] + by_kind[WorkKind.CLEANUP],
        "tracking_cents": by_kind[WorkKind.TRACKING],
        "returned_cents": returned,
        "tested_ideas": tested_count,
        "per_tested_idea_cents": round(total / tested_count) if tested_count else None,
    }


def results(bet: Bet, measured: Metric, work: list[dict]) -> dict | None:
    if bet.status not in ENDED:
        return None
    spent = {str(item["id"]): item["spent_cents"] for item in work}
    ideas = sorted(
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(
            bet=bet,
            goal_version=bet.goal_version,
            kind=WorkKind.IDEA,
            stage__in=(WorkStage.DONE, WorkStage.DROPPED),
        )
        .exclude(flag_key="", chosen_at__isnull=True),
        key=lambda item: (build_number(item) or math.inf, item.created_at),
    )
    recorded = bet.final_at is not None
    series: dict = bet.final_series if recorded else {"dates": measured.dates, "values": measured.values}
    values: list[float] = series.get("values") or []
    final = bet.final_value if recorded else (values[-1] if values else measured.current)
    first_merge = min((item.merged_at for item in ideas if item.merged_at), default=None)
    reached = bet.reached_at
    return {
        "recorded": recorded,
        "final_value": final,
        "final_at": bet.final_at,
        "dates": series.get("dates") or [],
        "values": values,
        "started_at": bet.baseline_at or bet.created_at,
        "ended_at": bet.final_at or bet.closed_at,
        "reached_at": reached,
        "met_at_start": meets(bet, bet.baseline_value)
        or bool(reached and (first_merge is None or reached < first_merge)),
        "ideas": [idea_result(item, spent) for item in ideas],
        "spend": spend_split(bet, sum(1 for item in ideas if tested(item.result.get("outcome")))),
    }


def detail(team: Team, user: User, bet: Bet) -> dict:
    scout = next(
        (item for item in signals.scouts_for_source(bet.team_id, "bets", f"{bet.id}:v{bet.goal_version}")),
        None,
    )
    row = entry(team, user, bet)
    actions = row["state"].actions
    work = work_entries(bet, user)
    return {
        **row,
        "goal_version": bet.goal_version,
        "goal_met_since": bet.goal_met_since,
        "closed_at": bet.closed_at,
        "results": results(bet, row["metric"], work),
        "work": work,
        "spend_history": spend_history(bet),
        "is_owner": user.id == bet.owner_id,
        "secondary_values": [metric(team, user, item["insight"], complete=True) for item in bet.secondary_metrics],
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
    owners = PostHogIdentity().members({bet.owner_id for bet in bets})
    entries = [entry(team, user, bet, owners=owners) for bet in bets]
    return {
        "bets": entries,
        "next_actions": sorted(
            [item for row in entries for item in row["state"].actions], key=lambda item: item["priority"]
        ),
        "north_star": metric(team, user, settings.north_star_insight, complete=True),
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
