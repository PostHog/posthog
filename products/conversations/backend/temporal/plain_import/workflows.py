"""Temporal workflows for Plain historical thread import."""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from products.conversations.backend.models.plain_import_job import PlainImportJob
    from products.conversations.backend.temporal.plain_import.activities import (
        EnumerateThreadsInput,
        ImportBatchInput,
        UpdateJobProgressInput,
        UpdateJobStatusInput,
        plain_import_batch_activity,
        plain_import_enumerate_threads_activity,
        plain_import_update_job_progress_activity,
        plain_import_update_job_status_activity,
    )
    from products.conversations.backend.temporal.plain_import.constants import (
        BATCH_SIZE,
        BATCH_WORKFLOW_ID_PREFIX,
        CONTINUE_AS_NEW_AFTER_PAGES,
        MAX_CONCURRENT_BATCH_WORKFLOWS,
        WORKFLOW_ID_PREFIX,
    )


IMPORT_FAILED_MESSAGE = "The import failed. Please try again or contact support if it persists."
IMPORT_CANCELLED_MESSAGE = "The import was cancelled."


@dataclass
class PlainImportCoordinatorInput:
    job_id: str
    team_id: int
    cursor: str | None = None
    pages_processed: int = 0
    pages_offset: int = 0
    dry_run: bool = False
    max_tickets: int | None = None
    default_email_channel_id: str | None = None
    task_queue: str = ""
    imported_offset: int = 0
    skipped_offset: int = 0
    failed_offset: int = 0


@dataclass
class PlainImportCoordinatorOutput:
    imported: int
    skipped: int
    failed: int


@dataclass
class PlainImportBatchWorkflowInput:
    job_id: str
    team_id: int
    thread_ids: list[str]
    dry_run: bool = False
    default_email_channel_id: str | None = None


RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))


@workflow.defn(name="plain-import-coordinator")
class PlainImportCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PlainImportCoordinatorInput:
        if not inputs:
            raise ValueError("PlainImportCoordinatorWorkflow requires input")
        loaded = json.loads(inputs[0])
        return PlainImportCoordinatorInput(**loaded)

    async def _run_batch_child(
        self, *, child_id: str, wf_input: PlainImportBatchWorkflowInput, task_queue: str
    ) -> PlainImportCoordinatorOutput:
        try:
            return await workflow.execute_child_workflow(
                PlainImportBatchWorkflow.run,
                wf_input,
                id=child_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=task_queue,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info("plain_import_batch_already_running", extra={"child_id": child_id})
            return PlainImportCoordinatorOutput(imported=0, skipped=0, failed=0)

    @workflow.run
    async def run(self, input: PlainImportCoordinatorInput) -> PlainImportCoordinatorOutput:
        if input.pages_processed == 0:
            await workflow.execute_activity(
                plain_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=PlainImportJob.Status.RUNNING),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )

        total_imported = input.imported_offset
        total_skipped = input.skipped_offset
        total_failed = input.failed_offset
        cursor = input.cursor
        pages_processed = input.pages_processed
        selected = 0

        try:
            while True:
                page = await workflow.execute_activity(
                    plain_import_enumerate_threads_activity,
                    EnumerateThreadsInput(job_id=input.job_id, cursor=cursor),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RETRY_POLICY,
                )
                cursor = page.next_cursor
                pages_processed += 1

                thread_ids = page.thread_ids
                reached_cap = False
                if input.max_tickets is not None:
                    remaining = input.max_tickets - selected
                    if remaining <= 0:
                        break
                    if len(thread_ids) >= remaining:
                        thread_ids = thread_ids[:remaining]
                        reached_cap = True
                selected += len(thread_ids)
                page.thread_ids = thread_ids

                if page.thread_ids:
                    await workflow.execute_activity(
                        plain_import_update_job_progress_activity,
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            total_delta=len(page.thread_ids),
                            export_cursor=cursor,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RETRY_POLICY,
                    )

                batches = [page.thread_ids[i : i + BATCH_SIZE] for i in range(0, len(page.thread_ids), BATCH_SIZE)]

                for window_start in range(0, len(batches), MAX_CONCURRENT_BATCH_WORKFLOWS):
                    window = batches[window_start : window_start + MAX_CONCURRENT_BATCH_WORKFLOWS]
                    results = await asyncio.gather(
                        *[
                            self._run_batch_child(
                                child_id=(
                                    f"{BATCH_WORKFLOW_ID_PREFIX}-{input.job_id}"
                                    f"-{input.pages_offset + pages_processed}-{window_start + offset}"
                                ),
                                wf_input=PlainImportBatchWorkflowInput(
                                    job_id=input.job_id,
                                    team_id=input.team_id,
                                    thread_ids=batch,
                                    dry_run=input.dry_run,
                                    default_email_channel_id=input.default_email_channel_id,
                                ),
                                task_queue=input.task_queue,
                            )
                            for offset, batch in enumerate(window)
                        ]
                    )

                    window_imported = sum(r.imported for r in results)
                    window_skipped = sum(r.skipped for r in results)
                    window_failed = sum(r.failed for r in results)
                    window_processed = sum(len(batch) for batch in window)
                    total_imported += window_imported
                    total_skipped += window_skipped
                    total_failed += window_failed

                    await workflow.execute_activity(
                        plain_import_update_job_progress_activity,
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            processed_delta=window_processed,
                            imported_delta=window_imported,
                            skipped_delta=window_skipped,
                            failed_delta=window_failed,
                            export_cursor=cursor,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RETRY_POLICY,
                    )

                if page.end_of_stream or reached_cap:
                    break

                if pages_processed >= CONTINUE_AS_NEW_AFTER_PAGES:
                    workflow.continue_as_new(
                        PlainImportCoordinatorInput(
                            job_id=input.job_id,
                            team_id=input.team_id,
                            cursor=cursor,
                            pages_processed=0,
                            pages_offset=input.pages_offset + pages_processed,
                            dry_run=input.dry_run,
                            max_tickets=None if input.max_tickets is None else input.max_tickets - selected,
                            default_email_channel_id=input.default_email_channel_id,
                            task_queue=input.task_queue,
                            imported_offset=total_imported,
                            skipped_offset=total_skipped,
                            failed_offset=total_failed,
                        )
                    )

            await workflow.execute_activity(
                plain_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=PlainImportJob.Status.COMPLETED),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            return PlainImportCoordinatorOutput(
                imported=total_imported,
                skipped=total_skipped,
                failed=total_failed,
            )
        except asyncio.CancelledError:
            workflow.logger.warning(
                "plain_import_coordinator_cancelled",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                plain_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=PlainImportJob.Status.FAILED,
                    latest_error=IMPORT_CANCELLED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise
        except Exception:
            workflow.logger.exception(
                "plain_import_coordinator_failed",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                plain_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=PlainImportJob.Status.FAILED,
                    latest_error=IMPORT_FAILED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise


@workflow.defn(name="plain-import-batch")
class PlainImportBatchWorkflow:
    @workflow.run
    async def run(self, input: PlainImportBatchWorkflowInput) -> PlainImportCoordinatorOutput:
        result = await workflow.execute_activity(
            plain_import_batch_activity,
            ImportBatchInput(
                job_id=input.job_id,
                team_id=input.team_id,
                thread_ids=input.thread_ids,
                dry_run=input.dry_run,
                default_email_channel_id=input.default_email_channel_id,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RETRY_POLICY,
        )
        return PlainImportCoordinatorOutput(
            imported=result.imported,
            skipped=result.skipped,
            failed=result.failed,
        )


def coordinator_workflow_id(team_id: int) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{team_id}"
