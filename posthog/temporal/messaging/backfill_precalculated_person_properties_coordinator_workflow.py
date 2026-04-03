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
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
)


@dataclasses.dataclass
class PersonIdRangesPageInputs:
    """Inputs for fetching a page of person ID ranges."""

    team_id: int
    batch_size: int  # persons per range
    page_size: int  # number of ranges to return per page
    after_person_id: str | None  # cursor: fetch persons with ID > this value, None for first page


@dataclasses.dataclass
class PersonIdRangesPageResult:
    """Result from fetching a page of person ID ranges."""

    ranges: list[tuple[str, str]]  # (start_id, end_id) pairs
    cursor: str | None  # last person ID in this page, None if no more data


@temporalio.activity.defn
async def get_person_id_ranges_page_activity(inputs: PersonIdRangesPageInputs) -> PersonIdRangesPageResult:
    """Fetch a page of person ID ranges for a team using cursor-based pagination."""
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    if inputs.batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {inputs.batch_size}")
    if inputs.page_size <= 0:
        raise ValueError(f"page_size must be positive, got {inputs.page_size}")

    limit = inputs.batch_size * inputs.page_size
    # Fetch one extra row to check if there's more data
    query_limit = limit + 1

    after_clause = "AND id > %(after_person_id)s" if inputs.after_person_id is not None else ""
    query = f"""
        SELECT id as person_id
        FROM person FINAL
        WHERE team_id = %(team_id)s
          AND is_deleted = 0
          {after_clause}
        ORDER BY id
        LIMIT %(limit)s
        FORMAT JSONEachRow
    """
    query_params: dict[str, object] = {"team_id": inputs.team_id, "limit": query_limit}
    if inputs.after_person_id is not None:
        query_params["after_person_id"] = inputs.after_person_id

    ranges: list[tuple[str, str]] = []
    current_batch_start: str | None = None
    current_batch_count = 0
    total_count = 0
    last_person_id: str | None = None
    has_more_data = False

    with tags_context(
        team_id=inputs.team_id,
        feature=Feature.BEHAVIORAL_COHORTS,
        product=Product.MESSAGING,
        query_type="person_id_ranges_page",
    ):
        async with get_client(team_id=inputs.team_id) as client:
            async for row in client.stream_query_as_jsonl(query, query_parameters=query_params):
                person_id = str(row["person_id"])

                # If we hit the limit + 1, we know there's more data, but don't process this row
                if total_count >= limit:
                    has_more_data = True
                    break

                last_person_id = person_id

                if current_batch_start is None:
                    current_batch_start = person_id
                    current_batch_count = 1
                else:
                    current_batch_count += 1

                total_count += 1

                if current_batch_count >= inputs.batch_size:
                    ranges.append((current_batch_start, person_id))
                    current_batch_start = None
                    current_batch_count = 0
                    # Heartbeat after each completed range to ensure regular heartbeats
                    temporalio.activity.heartbeat(f"Page: processed {total_count} persons, {len(ranges)} ranges")

            # Handle final partial batch
            if current_batch_start is not None and current_batch_count > 0 and last_person_id is not None:
                ranges.append((current_batch_start, last_person_id))

            # Final heartbeat to report completion
            if total_count > 0:
                temporalio.activity.heartbeat(f"Page: processed {total_count} persons, {len(ranges)} ranges")

    # Set cursor only if we know there's more data
    cursor = last_person_id if has_more_data else None

    return PersonIdRangesPageResult(ranges=ranges, cursor=cursor)


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow using ID-range based batching."""

    team_id: int
    filter_storage_key: str  # Redis key containing the filters
    cohort_ids: list[int]  # All cohort IDs being processed
    batch_size: int = 1000  # Persons per batch
    concurrent_workflows: int = 5  # Number of concurrent workflows to run

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": self.cohort_ids,
            "filter_storage_key": self.filter_storage_key,
            "batch_size": self.batch_size,
            "concurrent_workflows": self.concurrent_workflows,
        }


@temporalio.workflow.defn(name="backfill-precalculated-person-properties-coordinator")
class BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that processes persons using ID-range based batching.

    First fetches all person IDs for the team, then splits them into ranges
    and processes multiple ranges concurrently using child workflows.
    This approach provides better parallelism and predictable batch sizes.

    Child workflow ID format: {coordinator_workflow_id}-batch-{batch_number}
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
        """Parse inputs from the management command CLI."""
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    async def _start_child_workflow_for_range(
        self,
        inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
        workflow_logger,
        batch_number: int,
        start_person_id: str,
        end_person_id: str,
        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle],
    ) -> None:
        """Helper to start a child workflow for a person ID range."""
        child_workflow_id = f"{temporalio.workflow.info().workflow_id}-batch-{batch_number}"
        child_inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=inputs.team_id,
            filter_storage_key=inputs.filter_storage_key,
            cohort_ids=inputs.cohort_ids,
            batch_size=inputs.batch_size,
            start_person_id=start_person_id,
            end_person_id=end_person_id,
        )

        # Start child workflow
        child_handle = await temporalio.workflow.start_child_workflow(
            "backfill-precalculated-person-properties",
            child_inputs,
            id=child_workflow_id,
            task_queue=settings.MESSAGING_TASK_QUEUE,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
        )
        child_workflow_handles.append(child_handle)

        workflow_logger.info(
            f"Started batch {batch_number}: processing person IDs {start_person_id} to {end_person_id}"
        )

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
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow using paginated ID-range discovery.

        Fetches person ID ranges page by page and starts child workflows as
        ranges are discovered, respecting the concurrency limit throughout.
        """
        if inputs.batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {inputs.batch_size}")
        if inputs.concurrent_workflows <= 0:
            raise ValueError(f"concurrent_workflows must be positive, got {inputs.concurrent_workflows}")

        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for {len(cohort_ids)} cohorts "
            f"(team {inputs.team_id}, cohorts {cohort_ids}) with {inputs.concurrent_workflows} concurrent workflows"
        )

        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle] = []
        batch_number = 0
        workflows_scheduled = 0
        completed_count = 0
        failed_count = 0
        cursor: str | None = None
        has_more = True

        while has_more:
            page = await temporalio.workflow.execute_activity(
                get_person_id_ranges_page_activity,
                PersonIdRangesPageInputs(
                    team_id=inputs.team_id,
                    batch_size=inputs.batch_size,
                    page_size=inputs.concurrent_workflows,
                    after_person_id=cursor,
                ),
                start_to_close_timeout=dt.timedelta(minutes=10),
                heartbeat_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )

            if not page.ranges:
                if batch_number == 0:
                    workflow_logger.info("No persons found for team, nothing to process")
                break

            workflow_logger.info(
                f"Fetched page with {len(page.ranges)} ranges "
                f"(cursor: {cursor} -> {page.cursor}, total batches so far: {batch_number})"
            )

            for start_person_id, end_person_id in page.ranges:
                batch_number += 1

                # Respect concurrency limit - wait for a slot before starting
                if len(child_workflow_handles) >= inputs.concurrent_workflows:
                    done, _ = await asyncio.wait(child_workflow_handles, return_when=asyncio.FIRST_COMPLETED)
                    c, f = await self._drain_completed(done, child_workflow_handles, workflow_logger)
                    completed_count += c
                    failed_count += f

                await self._start_child_workflow_for_range(
                    inputs, workflow_logger, batch_number, start_person_id, end_person_id, child_workflow_handles
                )
                workflows_scheduled += 1

            cursor = page.cursor
            if cursor is None:
                has_more = False

        # Wait for all remaining child workflows
        workflow_logger.info(
            f"All workflows scheduled ({workflows_scheduled}), waiting for remaining {len(child_workflow_handles)}"
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
                f"{failed_count} child workflows failed; some person ID ranges were not processed.",
                non_retryable=False,
            )

        workflow_logger.info(
            f"Coordinator workflow completed successfully for team {inputs.team_id}: "
            f"processed {batch_number} ranges with {inputs.concurrent_workflows} concurrent workflows"
        )
