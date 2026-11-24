"""Temporal workflows for Pylon historical issue import."""

from __future__ import annotations

import json
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen

with workflow.unsafe.imports_passed_through():
    from products.conversations.backend.models.pylon_import_job import PylonImportJob
    from products.conversations.backend.temporal.pylon_import.activities import (
        EnumerateIssuesInput,
        ImportBatchInput,
        UpdateJobProgressInput,
        UpdateJobStatusInput,
        pylon_import_batch_activity,
        pylon_import_enumerate_issues_activity,
        pylon_import_update_job_progress_activity,
        pylon_import_update_job_status_activity,
    )
    from products.conversations.backend.temporal.pylon_import.constants import (
        BATCH_SIZE,
        BATCH_WORKFLOW_ID_PREFIX,
        CONTINUE_AS_NEW_AFTER_PAGES,
        MAX_CONCURRENT_BATCH_WORKFLOWS,
    )


IMPORT_FAILED_MESSAGE = "The import failed. Please try again or contact support if it persists."
IMPORT_CANCELLED_MESSAGE = "The import was cancelled."


@frozen
class PylonImportCoordinatorInput:
    job_id: str
    team_id: int
    cursor: str | None = None
    pages_processed: int = 0
    # Cumulative pages from prior continue-as-new generations. Child workflow IDs use the absolute
    # page index so a new generation can't regenerate an ID that already completed.
    pages_offset: int = 0
    default_email_channel_id: str | None = None
    # Worker queue for batch child workflows, passed in at start time so the coordinator never
    # reads django.conf.settings inside the sandbox.
    task_queue: str = ""
    imported_offset: int = 0
    skipped_offset: int = 0
    failed_offset: int = 0
    total_offset: int = 0
    processed_offset: int = 0


@frozen
class PylonImportCoordinatorOutput:
    imported: int
    skipped: int
    failed: int


@frozen
class PylonImportBatchWorkflowInput:
    job_id: str
    team_id: int
    issue_ids: list[str]
    default_email_channel_id: str | None = None


RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))
# Lets Temporal notice a dead worker well before the 30-minute start-to-close timeout.
BATCH_HEARTBEAT_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name="pylon-import-coordinator")
class PylonImportCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PylonImportCoordinatorInput:
        if not inputs:
            raise ValueError("PylonImportCoordinatorWorkflow requires input")
        loaded = json.loads(inputs[0])
        return PylonImportCoordinatorInput(**loaded)

    async def _run_batch_child(
        self, *, child_id: str, wf_input: PylonImportBatchWorkflowInput, task_queue: str
    ) -> PylonImportCoordinatorOutput:
        try:
            return await workflow.execute_child_workflow(
                PylonImportBatchWorkflow.run,
                wf_input,
                id=child_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=task_queue,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info("pylon_import_batch_already_running", extra={"child_id": child_id})
            return PylonImportCoordinatorOutput(imported=0, skipped=0, failed=0)

    async def _publish_progress(self, progress: UpdateJobProgressInput) -> None:
        await workflow.execute_activity(
            pylon_import_update_job_progress_activity,
            progress,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RETRY_POLICY,
        )

    @workflow.run
    async def run(self, input: PylonImportCoordinatorInput) -> PylonImportCoordinatorOutput:
        total_imported = input.imported_offset
        total_skipped = input.skipped_offset
        total_failed = input.failed_offset
        total_issues = input.total_offset
        total_processed = input.processed_offset
        cursor = input.cursor
        pages_processed = input.pages_processed

        try:
            if input.pages_processed == 0 and input.pages_offset == 0:
                await workflow.execute_activity(
                    pylon_import_update_job_status_activity,
                    UpdateJobStatusInput(job_id=input.job_id, status=PylonImportJob.Status.RUNNING),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RETRY_POLICY,
                )

            while True:
                page = await workflow.execute_activity(
                    pylon_import_enumerate_issues_activity,
                    EnumerateIssuesInput(job_id=input.job_id, cursor=cursor),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RETRY_POLICY,
                )
                cursor = page.next_cursor
                pages_processed += 1

                # Progress carries absolute totals from workflow state, so an activity retry after
                # a committed write rewrites the same values instead of counting them twice.
                if page.issue_ids:
                    total_issues += len(page.issue_ids)
                    await self._publish_progress(
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            total=total_issues,
                            processed=total_processed,
                            imported=total_imported,
                            skipped=total_skipped,
                            failed=total_failed,
                            export_cursor=cursor,
                        ),
                    )

                ids = page.issue_ids
                batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]

                for window_start in range(0, len(batches), MAX_CONCURRENT_BATCH_WORKFLOWS):
                    window = batches[window_start : window_start + MAX_CONCURRENT_BATCH_WORKFLOWS]
                    results = await asyncio.gather(
                        *[
                            self._run_batch_child(
                                child_id=(
                                    f"{BATCH_WORKFLOW_ID_PREFIX}-{input.job_id}"
                                    f"-{input.pages_offset + pages_processed}-{window_start + offset}"
                                ),
                                wf_input=PylonImportBatchWorkflowInput(
                                    job_id=input.job_id,
                                    team_id=input.team_id,
                                    issue_ids=batch,
                                    default_email_channel_id=input.default_email_channel_id,
                                ),
                                task_queue=input.task_queue,
                            )
                            for offset, batch in enumerate(window)
                        ]
                    )

                    total_imported += sum(r.imported for r in results)
                    total_skipped += sum(r.skipped for r in results)
                    total_failed += sum(r.failed for r in results)
                    total_processed += sum(len(batch) for batch in window)

                    await self._publish_progress(
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            total=total_issues,
                            processed=total_processed,
                            imported=total_imported,
                            skipped=total_skipped,
                            failed=total_failed,
                            export_cursor=cursor,
                        ),
                    )

                if cursor is None:
                    break

                if pages_processed >= CONTINUE_AS_NEW_AFTER_PAGES:
                    workflow.continue_as_new(
                        PylonImportCoordinatorInput(
                            job_id=input.job_id,
                            team_id=input.team_id,
                            cursor=cursor,
                            pages_processed=0,
                            pages_offset=input.pages_offset + pages_processed,
                            default_email_channel_id=input.default_email_channel_id,
                            task_queue=input.task_queue,
                            imported_offset=total_imported,
                            skipped_offset=total_skipped,
                            failed_offset=total_failed,
                            total_offset=total_issues,
                            processed_offset=total_processed,
                        )
                    )

            await workflow.execute_activity(
                pylon_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=PylonImportJob.Status.COMPLETED),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            return PylonImportCoordinatorOutput(imported=total_imported, skipped=total_skipped, failed=total_failed)
        except asyncio.CancelledError:
            # Cancellation subclasses BaseException, so `except Exception` can't see it. Record a
            # terminal state so the settings UI doesn't poll "Syncing" forever.
            workflow.logger.warning(
                "pylon_import_coordinator_cancelled",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                pylon_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=PylonImportJob.Status.FAILED,
                    latest_error=IMPORT_CANCELLED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise
        except Exception:
            # Raw exception strings can carry hostnames or request details, so log the full error
            # server-side and persist only a generic message for the admin-facing UI.
            workflow.logger.exception(
                "pylon_import_coordinator_failed",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                pylon_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=PylonImportJob.Status.FAILED,
                    latest_error=IMPORT_FAILED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise


@workflow.defn(name="pylon-import-batch")
class PylonImportBatchWorkflow:
    @workflow.run
    async def run(self, input: PylonImportBatchWorkflowInput) -> PylonImportCoordinatorOutput:
        result = await workflow.execute_activity(
            pylon_import_batch_activity,
            ImportBatchInput(
                job_id=input.job_id,
                team_id=input.team_id,
                issue_ids=input.issue_ids,
                default_email_channel_id=input.default_email_channel_id,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=BATCH_HEARTBEAT_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return PylonImportCoordinatorOutput(imported=result.imported, skipped=result.skipped, failed=result.failed)
