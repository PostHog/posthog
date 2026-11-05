import datetime as dt

import dagster
import pydantic

from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.runner import (
    RollupDayRefused,
    clean_up,
    plan_requested_days,
    plan_scheduled_days,
    published_days_in_retention,
    run_rollup_day,
)

DAILY_ROLLUP_CRON = "0 1 * * *"
# A first run fills every day that retention keeps, one ClickHouse day scan after another.
MAX_RUNTIME_SECONDS = 6 * 60 * 60
# A retry plans again from the published days, so it refills the refresh day that a transient error failed.
# The next scheduled run does not, because it refreshes a later day.
FILL_RETRY_POLICY = dagster.RetryPolicy(max_retries=2, delay=15 * 60)


class DailyRollupConfig(dagster.Config):
    days: list[str] = pydantic.Field(
        default_factory=list,
        description=(
            "UTC days to fill, as YYYY-MM-DD. Leave empty to publish yesterday, refresh the day before, "
            "and fill every missing day that retention keeps."
        ),
    )
    force: bool = pydantic.Field(
        default=False,
        description="Publish a day even when it has fewer than half the rows of the recent median.",
    )


@frozen
class DailyRollupDefinitions:
    job: dagster.JobDefinition
    schedule: dagster.ScheduleDefinition


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def build_daily_rollup_definitions(rollup: type[DailyRollup], *, owner: JobOwners) -> DailyRollupDefinitions:
    """A daily job that fills one rollup table from ClickHouse, and its schedule.

    Every planned day runs even when an earlier one fails, and clean-up runs last. The op then fails
    if any day failed, which leaves that day as it was. Dagster retries it unless every failed day was
    refused, because a refused day fails the same way again.
    """
    table = rollup.table()

    @dagster.op(name=f"fill_{table}", retry_policy=FILL_RETRY_POLICY)
    def fill_rollup(context: dagster.OpExecutionContext, config: DailyRollupConfig) -> None:
        today = _today()
        if config.days:
            plan = plan_requested_days([dt.date.fromisoformat(day) for day in config.days], today=today)
        else:
            plan = plan_scheduled_days(rollup, today=today, published=published_days_in_retention(rollup, today=today))
        context.log.info(f"Filling {table} for {', '.join(f'{step.day} ({step.mode})' for step in plan)}")

        failures: list[str] = []
        only_refusals = True
        for step in plan:
            try:
                result = run_rollup_day(rollup, step, force=config.force)
            except Exception as error:
                context.log.exception(f"Filling {table} for {step.day} failed")
                failures.append(f"{step.day}: {error}")
                only_refusals = only_refusals and isinstance(error, RollupDayRefused)
                continue
            context.log.info(f"{table} {result.day}: {result.outcome}, {result.rows:,} rows, {result.events:,} events")

        deleted_rows = clean_up(rollup, today=today)
        context.log.info(f"Clean-up removed {deleted_rows:,} rows of {table}")
        if failures:
            raise dagster.Failure(
                description=f"{len(failures)} of {len(plan)} days of {table} failed. "
                "Launch the job with `days` to fill them again, and `force` to publish a refused day. "
                + "; ".join(failures),
                allow_retries=not only_refusals,
            )

    @dagster.job(
        name=f"{table}_job",
        description=f"Fills the {table} daily rollup from ClickHouse events.",
        tags={"owner": owner.value, "dagster/max_runtime": MAX_RUNTIME_SECONDS},
    )
    def fill_rollup_job() -> None:
        fill_rollup()

    schedule = dagster.ScheduleDefinition(
        name=f"{table}_schedule",
        job=fill_rollup_job,
        cron_schedule=DAILY_ROLLUP_CRON,
        execution_timezone="UTC",
        default_status=dagster.DefaultScheduleStatus.RUNNING,
    )
    return DailyRollupDefinitions(job=fill_rollup_job, schedule=schedule)
