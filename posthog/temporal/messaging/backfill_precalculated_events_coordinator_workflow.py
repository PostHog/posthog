import asyncio
import datetime as dt
import dataclasses
from typing import Any

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.messaging.backfill_precalculated_events_workflow import BackfillPrecalculatedEventsInputs


@dataclasses.dataclass
class EventDateCheckInputs:
    """Inputs for checking whether a day has already been backfilled."""

    team_id: int
    condition_hashes: list[str]
    date: str  # YYYY-MM-DD format


@dataclasses.dataclass
class EventDateCheckResult:
    """Result from checking whether a day is already backfilled."""

    date: str
    already_backfilled: bool


@temporalio.activity.defn
async def check_day_already_backfilled_activity(inputs: EventDateCheckInputs) -> EventDateCheckResult:
    """Check whether all conditions for a given day already have data in precalculated_events.

    This is a cheap COUNT query that catches the common re-run case without per-event lookups.
    """
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    if not inputs.condition_hashes:
        return EventDateCheckResult(date=inputs.date, already_backfilled=False)

    query = """
        SELECT count(DISTINCT condition) as condition_count
        FROM precalculated_events
        WHERE team_id = %(team_id)s
          AND date = %(date)s
          AND condition IN %(condition_hashes)s
    """
    query_params = {
        "team_id": inputs.team_id,
        "date": inputs.date,
        "condition_hashes": inputs.condition_hashes,
    }

    with tags_context(
        team_id=inputs.team_id,
        feature=Feature.BEHAVIORAL_COHORTS,
        product=Product.MESSAGING,
        query_type="event_backfill_day_check",
    ):
        async with get_client(team_id=inputs.team_id) as client:
            result = await client.read_query(query, query_params)
            condition_count = int(result.strip()) if result.strip() else 0

    already_backfilled = condition_count >= len(inputs.condition_hashes)
    return EventDateCheckResult(date=inputs.date, already_backfilled=already_backfilled)


@dataclasses.dataclass
class BackfillPrecalculatedEventsCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    team_id: int
    filter_storage_key: str
    cohort_ids: list[int]
    condition_hashes: list[str]
    days_to_backfill: int
    concurrent_workflows: int = 5
    force_reprocess: bool = False

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": self.cohort_ids,
            "filter_storage_key": self.filter_storage_key,
            "days_to_backfill": self.days_to_backfill,
            "concurrent_workflows": self.concurrent_workflows,
            "condition_count": len(self.condition_hashes),
            "force_reprocess": self.force_reprocess,
        }


@temporalio.workflow.defn(name="backfill-precalculated-events-coordinator")
class BackfillPrecalculatedEventsCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that partitions a time range into daily chunks
    and distributes them across child workflows with concurrency control.

    Child workflow ID format: {coordinator_workflow_id}-day-{YYYY-MM-DD}
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedEventsCoordinatorInputs:
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    async def _start_child_workflow_for_day(
        self,
        inputs: BackfillPrecalculatedEventsCoordinatorInputs,
        workflow_logger,
        day_start: dt.datetime,
        day_end: dt.datetime,
        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle],
    ) -> None:
        date_str = day_start.strftime("%Y-%m-%d")
        child_workflow_id = f"{temporalio.workflow.info().workflow_id}-day-{date_str}"
        child_inputs = BackfillPrecalculatedEventsInputs(
            team_id=inputs.team_id,
            filter_storage_key=inputs.filter_storage_key,
            cohort_ids=inputs.cohort_ids,
            start_time=day_start.isoformat(),
            end_time=day_end.isoformat(),
        )

        child_handle = await temporalio.workflow.start_child_workflow(
            "backfill-precalculated-events",
            child_inputs,
            id=child_workflow_id,
            task_queue=settings.MESSAGING_TASK_QUEUE,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
        )
        child_workflow_handles.append(child_handle)

        workflow_logger.info(f"Started child workflow for {date_str}")

    async def _drain_completed(
        self,
        done: set[temporalio.workflow.ChildWorkflowHandle],
        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle],
        workflow_logger,
    ) -> tuple[int, int]:
        """Await completed handles and return (completed_count, failed_count) delta."""
        completed = 0
        failed = 0
        for handle in done:
            try:
                await handle
                completed += 1
                workflow_logger.info("Child workflow completed successfully")
            except Exception as e:
                failed += 1
                workflow_logger.exception(f"Child workflow failed: {e}")
            finally:
                child_workflow_handles.remove(handle)
        return completed, failed

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedEventsCoordinatorInputs) -> None:
        if inputs.days_to_backfill <= 0:
            raise ValueError(f"days_to_backfill must be positive, got {inputs.days_to_backfill}")
        if inputs.concurrent_workflows <= 0:
            raise ValueError(f"concurrent_workflows must be positive, got {inputs.concurrent_workflows}")

        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting event backfill coordinator for team {inputs.team_id}: "
            f"{inputs.days_to_backfill} days, {len(inputs.cohort_ids)} cohorts, "
            f"{inputs.concurrent_workflows} concurrent workflows"
        )

        # Compute the daily time ranges to process (most recent first for faster value delivery)
        now = temporalio.workflow.now()
        day_ranges: list[tuple[dt.datetime, dt.datetime]] = []
        for day_offset in range(inputs.days_to_backfill):
            day_start = (now - dt.timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + dt.timedelta(days=1)
            # For today's partial day, use now as the end
            if day_offset == 0:
                day_end = now
            day_ranges.append((day_start, day_end))

        workflow_logger.info(
            f"Partitioned into {len(day_ranges)} daily chunks, "
            f"from {day_ranges[-1][0].strftime('%Y-%m-%d')} to {day_ranges[0][1].strftime('%Y-%m-%d')}"
        )

        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle] = []
        workflows_scheduled = 0
        completed_count = 0
        failed_count = 0
        days_skipped = 0

        for day_start, day_end in day_ranges:
            date_str = day_start.strftime("%Y-%m-%d")

            # Check if this day is already backfilled (skippable unless force_reprocess is set)
            if not inputs.force_reprocess:
                check_result = await temporalio.workflow.execute_activity(
                    check_day_already_backfilled_activity,
                    EventDateCheckInputs(
                        team_id=inputs.team_id,
                        condition_hashes=inputs.condition_hashes,
                        date=date_str,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )

                if check_result.already_backfilled:
                    workflow_logger.info(f"Skipping {date_str}: already backfilled")
                    days_skipped += 1
                    continue

            # Respect concurrency limit
            if len(child_workflow_handles) >= inputs.concurrent_workflows:
                done, _ = await asyncio.wait(child_workflow_handles, return_when=asyncio.FIRST_COMPLETED)
                c, f = await self._drain_completed(done, child_workflow_handles, workflow_logger)
                completed_count += c
                failed_count += f

            await self._start_child_workflow_for_day(
                inputs, workflow_logger, day_start, day_end, child_workflow_handles
            )
            workflows_scheduled += 1

        # Wait for all remaining child workflows
        workflow_logger.info(
            f"All workflows scheduled ({workflows_scheduled}), "
            f"waiting for remaining {len(child_workflow_handles)}, "
            f"skipped {days_skipped} already-backfilled days"
        )
        while child_workflow_handles:
            done, _ = await asyncio.wait(child_workflow_handles, return_when=asyncio.FIRST_COMPLETED)
            c, f = await self._drain_completed(done, child_workflow_handles, workflow_logger)
            completed_count += c
            failed_count += f

        if failed_count > 0:
            workflow_logger.warning(
                f"Coordinator completed with {failed_count} failed child workflows out of {workflows_scheduled} total"
            )
            raise temporalio.exceptions.ApplicationError(
                f"{failed_count} child workflows failed; some days were not processed.",
                non_retryable=False,
            )

        workflow_logger.info(
            f"Coordinator completed successfully for team {inputs.team_id}: "
            f"processed {workflows_scheduled} days, skipped {days_skipped} already-backfilled days"
        )
