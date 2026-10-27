from uuid import UUID

from django.db import transaction

import structlog

from products.experiments.backend.facade.launch_signals import connect_source_experiment_changes
from products.signals.backend.facade.source_events import register_scout_source, scout_report_filed
from products.tasks.backend.facade.task_run_signals import (
    connect_task_run_cost_updated,
    connect_task_run_finished,
    register_task_run_start_guard,
    task_has_origin_key,
)

logger = structlog.get_logger(__name__)


def run_changed(*, run_id: UUID, team_id: int, **kwargs: object) -> None:
    from .logic.spend import bet_for_run  # noqa: PLC0415 — keeps the task and scout facades off Django startup
    from .tasks.tasks import reconcile_bet_run  # noqa: PLC0415 — avoids importing Celery during app registration

    try:
        if bet_for_run(team_id, run_id) is not None:
            transaction.on_commit(lambda: reconcile_bet_run.delay(team_id, str(run_id)), robust=True)
    except Exception:
        logger.exception("bets.run_dispatch_failed", team_id=team_id, run_id=str(run_id))


def experiment_changed(*, team_id: int, experiment_id: int, **kwargs: object) -> None:
    from .db import WRITER_DB  # noqa: PLC0415 - experiment events register before the product's models load
    from .facade.api import wake  # noqa: PLC0415 - event registration must not import product coordinators
    from .models import WorkItem  # noqa: PLC0415 - experiment events register before the product's models load

    for work in (
        WorkItem.objects.for_team(team_id).using(WRITER_DB).filter(experiment_id=experiment_id).select_related("bet")
    ):
        wake(work.bet)


def task_start_guard(task_id: str, team_id: int, user_id: int | None) -> str | None:
    from products.signals.backend.facade import api as signals  # noqa: PLC0415 — keeps the facade off Django startup

    from .logic.guards import task_start_refusal  # noqa: PLC0415 — keeps product facades off Django startup

    if task_has_origin_key(task_id, team_id, "bets:"):
        return task_start_refusal(task_id, team_id)
    if signals.task_has_source_report(team_id, task_id, "bets"):
        return "Bets builds its own ideas. This report does not start its own task."
    return None


def scout_start_guard(team_id: int, source_id: str) -> str | None:
    from .logic.scout import scout_refusal  # noqa: PLC0415 — keeps product facades off Django startup

    return scout_refusal(team_id, source_id)


def run_spend_limit(run_id: str, team_id: int) -> int | None:
    from .logic.spend import admit_gateway_spend  # noqa: PLC0415 - gateway admission is not needed on Django startup

    return admit_gateway_spend(team_id, UUID(run_id))


def bet_scout_context(team_id: int, source_id: str) -> str:
    from .logic.scout import scout_context  # noqa: PLC0415 — keeps product facades off Django startup

    return scout_context(team_id, source_id)


def connect_receivers() -> None:
    connect_source_experiment_changes(experiment_changed, flag_prefix="bet-", dispatch_uid="bets.experiment_changed")
    connect_task_run_cost_updated(run_changed, dispatch_uid="bets.gateway_cost_updated")
    connect_task_run_finished(run_changed, dispatch_uid="bets.task_finished")
    scout_report_filed.connect(run_changed, dispatch_uid="bets.scout_report_filed")
    register_task_run_start_guard(task_start_guard, name="bets", spend_limit=run_spend_limit)
    register_scout_source("bets", guard=scout_start_guard, context=bet_scout_context)
