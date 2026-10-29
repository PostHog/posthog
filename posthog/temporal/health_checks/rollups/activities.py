from __future__ import annotations

import datetime as dt

from django.db import close_old_connections

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.health_checks.rollups.fill import fill_day
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.freshness import invalidate_published_days
from posthog.temporal.health_checks.rollups.inputs import (
    DailyRollupWorkflowInputs,
    RollupPlan,
    RollupStep,
    RollupStepMode,
    RollupStepResult,
)
from posthog.temporal.health_checks.rollups.registry import all_rollup_tables, get_rollup
from posthog.temporal.health_checks.rollups.store import (
    day_stats,
    delete_days_before,
    delete_rollup_rows_for_teams,
    publish_day,
)
from posthog.temporal.health_checks.rollups.validation import day_moved, refusal_reason

logger = structlog.get_logger(__name__)

ROLLUP_DAY_REFUSED_ERROR_TYPE = "DailyRollupDayRefused"
MEDIAN_HISTORY_DAYS = 7
DAILY_STEPS: tuple[tuple[int, RollupStepMode], ...] = ((1, "publish"), (2, "refresh"))


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def build_plan(inputs: DailyRollupWorkflowInputs, *, today: dt.date) -> RollupPlan:
    tables = inputs.tables or all_rollup_tables()
    for table in tables:
        get_rollup(table)

    if inputs.days:
        days = sorted({dt.date.fromisoformat(day) for day in inputs.days})
        future = [day for day in days if day >= today]
        if future:
            raise ValueError(f"Cannot fill a day that has not ended: {', '.join(d.isoformat() for d in future)}")
        steps = [
            RollupStep(table=table, day=day.isoformat(), mode="publish", force=inputs.force)
            for table in tables
            for day in days
        ]
    else:
        steps = [
            RollupStep(table=table, day=(today - dt.timedelta(days=age)).isoformat(), mode=mode, force=inputs.force)
            for age, mode in DAILY_STEPS
            for table in tables
        ]
    return RollupPlan(steps=steps, retention_tables=list(tables))


@temporalio.activity.defn
async def plan_daily_rollup_run(inputs: DailyRollupWorkflowInputs) -> RollupPlan:
    return build_plan(inputs, today=_today())


def _live_team_ids() -> set[int]:
    return set(Team.objects.values_list("id", flat=True))


def run_rollup_step(step: RollupStep) -> RollupStepResult:
    """Fill one day of one rollup and publish it unless it is refused or unchanged.

    Every slow part, the ClickHouse reads, runs before the Postgres transaction opens.
    """
    rollup: type[DailyRollup] = get_rollup(step.table)
    day = dt.date.fromisoformat(step.day)
    live_team_ids = _live_team_ids()
    fill = fill_day(rollup, day, live_team_ids)
    try:
        if step.mode == "refresh" and not day_moved(day_stats(rollup, [day]).get(day), fill):
            logger.info("daily rollup day unchanged", table=step.table, day=step.day, rows=fill.row_count)
            return RollupStepResult(
                table=step.table, day=step.day, outcome="unchanged", rows=fill.row_count, events=fill.event_count
            )

        history_days = [day - dt.timedelta(days=offset) for offset in range(1, MEDIAN_HISTORY_DAYS + 1)]
        stats = day_stats(rollup, history_days)
        history = [stats[history_day] for history_day in history_days if history_day in stats]
        reason = refusal_reason(rollup, fill, history, force=step.force)
        if reason is not None:
            logger.warning("daily rollup day refused", table=step.table, day=step.day, reason=reason)
            raise ApplicationError(
                f"Refused to publish {step.table} for {step.day}: {reason}",
                type=ROLLUP_DAY_REFUSED_ERROR_TYPE,
                non_retryable=True,
            )

        publish_day(rollup, fill)
        deleted_during_fill = live_team_ids - _live_team_ids()
        if deleted_during_fill:
            delete_rollup_rows_for_teams(rollup.model, sorted(deleted_during_fill))
        invalidate_published_days(rollup.model)
        return RollupStepResult(
            table=step.table, day=step.day, outcome="published", rows=fill.row_count, events=fill.event_count
        )
    finally:
        fill.close()


@database_sync_to_async
def _run_rollup_step_sync(step: RollupStep) -> RollupStepResult:
    close_old_connections()
    return run_rollup_step(step)


@temporalio.activity.defn
async def run_daily_rollup_step(step: RollupStep) -> RollupStepResult:
    async with Heartbeater():
        return await _run_rollup_step_sync(step)


def apply_retention(table: str, *, today: dt.date) -> int:
    rollup = get_rollup(table)
    deleted = delete_days_before(rollup, today - dt.timedelta(days=rollup.retention_days))
    if deleted:
        invalidate_published_days(rollup.model)
    return deleted


@database_sync_to_async
def _apply_retention_sync(table: str) -> int:
    close_old_connections()
    return apply_retention(table, today=_today())


@temporalio.activity.defn
async def apply_daily_rollup_retention(table: str) -> int:
    async with Heartbeater():
        return await _apply_retention_sync(table)
