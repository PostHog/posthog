from datetime import timedelta
from uuid import UUID

from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks
from products.tasks.backend.facade.billing import get_task_cost, get_task_run_cost
from products.tasks.backend.facade.task_run_signals import task_has_origin_key

from ..db import WRITER_DB
from ..models import Bet, WorkItem
from .ledger import settle_usage, totals
from .stages import LIVE

SCOUT_BUDGET_CENTS = 1200


UNKNOWN_COST_GRACE = timedelta(hours=1)


@frozen
class UsageSource:
    reference: str
    cumulative_cents: int | None
    work: WorkItem | None = None
    waiting: bool = False


def usage_sources(bet: Bet) -> list[UsageSource]:
    sources: list[UsageSource] = []
    seen: set[UUID] = set()
    works = list(WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet, task_id__isnull=False))
    runs = tasks.get_latest_run_by_task([str(work.task_id) for work in works])
    for work in works:
        if work.task_id is None or work.task_id in seen or str(work.task_id) not in runs:
            continue
        seen.add(work.task_id)
        cost = get_task_cost(team_id=bet.team_id, task_id=work.task_id)
        waiting = recent(runs[str(work.task_id)])
        sources.extend(
            UsageSource(reference=f"task:{work.task_id}:{part}", cumulative_cents=cents, work=work, waiting=waiting)
            for part, cents in (("tokens", cost.token_cost), ("compute", cost.compute_cost))
        )
    source_ids = [f"{bet.id}:v{version}" for version in range(1, bet.goal_version + 1)]
    for run_id in signals.scout_run_ids_for_source(bet.team_id, "bets", source_ids):
        run = tasks.get_task_run(run_id, team_id=bet.team_id)
        if run is None or run.task_id in seen:
            continue
        cost = get_task_run_cost(team_id=bet.team_id, run_id=run_id)
        waiting = recent(run)
        sources.extend(
            UsageSource(reference=f"scout:{run_id}:{part}", cumulative_cents=cents, waiting=waiting)
            for part, cents in (("tokens", cost.token_cost), ("compute", cost.compute_cost))
        )
    return sources


def recent(run: object) -> bool:
    if not getattr(run, "is_terminal", False):
        return True
    finished = (
        getattr(run, "completed_at", None) or getattr(run, "updated_at", None) or getattr(run, "created_at", None)
    )
    return finished is None or timezone.now() - finished < UNKNOWN_COST_GRACE


def spend_pending(bet: Bet, work: WorkItem | None = None) -> bool:
    return any(
        source.cumulative_cents is None and source.waiting
        for source in usage_sources(bet)
        if work is None or (source.work is not None and source.work.id == work.id)
    )


def reconcile_spend(bet: Bet) -> None:
    for source in usage_sources(bet):
        if source.cumulative_cents is not None:
            settle_usage(bet, source.reference, source.cumulative_cents, source.work)


def bet_for_run(team_id: int, run_id: UUID) -> Bet | None:
    task_id = tasks.get_task_id_for_run(run_id, team_id)
    managed_task = task_id and (
        task_has_origin_key(task_id, team_id, "bets:") or signals.task_has_source_report(team_id, task_id, "bets")
    )
    work = WorkItem.objects.for_team(team_id).using(WRITER_DB).filter(task_id=task_id).first() if managed_task else None
    if work:
        return Bet.objects.for_team(team_id).using(WRITER_DB).get(id=work.bet_id)
    source = signals.scout_source_for_run(team_id, run_id, "bets")
    if not source:
        return None
    try:
        bet_id = UUID(source.split(":v", 1)[0])
    except ValueError:
        return None
    return Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=bet_id).first()


def admit_gateway_spend(team_id: int, run_id: UUID) -> int | None:
    bet = bet_for_run(team_id, run_id)
    if bet is None:
        return None
    if bet.status not in LIVE:
        raise ValueError("The bet is not running.")
    run = tasks.get_task_run(run_id, team_id=team_id)
    work = (
        WorkItem.objects.for_team(team_id).using(WRITER_DB).filter(bet=bet, task_id=run.task_id).first()
        if run
        else None
    )
    held = (
        totals(team_id, work=work).reserved_cents
        if work
        else min(SCOUT_BUDGET_CENTS, totals(team_id, bet).available_cents)
    )
    if held <= 1:
        raise ValueError("This run has no budget left.")
    return max(1, held * 4 // 5)
