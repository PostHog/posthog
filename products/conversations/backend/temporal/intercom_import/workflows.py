"""Temporal workflows for Intercom historical conversation import."""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from products.conversations.backend.models.intercom_import_job import IntercomImportJob
    from products.conversations.backend.temporal.intercom_import.activities import (
        EnumerateConversationsInput,
        ImportBatchInput,
        UpdateJobProgressInput,
        UpdateJobStatusInput,
        intercom_import_batch_activity,
        intercom_import_enumerate_conversations_activity,
        intercom_import_update_job_progress_activity,
        intercom_import_update_job_status_activity,
    )
    from products.conversations.backend.temporal.intercom_import.constants import (
        BATCH_SIZE,
        BATCH_WORKFLOW_ID_PREFIX,
        CONTINUE_AS_NEW_AFTER_PAGES,
        MAX_CONCURRENT_BATCH_WORKFLOWS,
    )


IMPORT_FAILED_MESSAGE = "The import failed. Please try again or contact support if it persists."
IMPORT_CANCELLED_MESSAGE = "The import was cancelled."


@dataclass
class IntercomImportCoordinatorInput:
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


@dataclass
class IntercomImportCoordinatorOutput:
    imported: int
    skipped: int
    failed: int


@dataclass
class IntercomImportBatchWorkflowInput:
    job_id: str
    team_id: int
    conversation_ids: list[str]
    default_email_channel_id: str | None = None


RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))


@workflow.defn(name="intercom-import-coordinator")
class IntercomImportCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntercomImportCoordinatorInput:
        if not inputs:
            raise ValueError("IntercomImportCoordinatorWorkflow requires input")
        loaded = json.loads(inputs[0])
        return IntercomImportCoordinatorInput(**loaded)

    async def _run_batch_child(
        self, *, child_id: str, wf_input: IntercomImportBatchWorkflowInput, task_queue: str
    ) -> IntercomImportCoordinatorOutput:
        try:
            return await workflow.execute_child_workflow(
                IntercomImportBatchWorkflow.run,
                wf_input,
                id=child_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=task_queue,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info("intercom_import_batch_already_running", extra={"child_id": child_id})
            return IntercomImportCoordinatorOutput(imported=0, skipped=0, failed=0)

    @workflow.run
    async def run(self, input: IntercomImportCoordinatorInput) -> IntercomImportCoordinatorOutput:
        if input.pages_processed == 0 and input.pages_offset == 0:
            await workflow.execute_activity(
                intercom_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=IntercomImportJob.Status.RUNNING),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )

        total_imported = input.imported_offset
        total_skipped = input.skipped_offset
        total_failed = input.failed_offset
        cursor = input.cursor
        pages_processed = input.pages_processed

        try:
            while True:
                page = await workflow.execute_activity(
                    intercom_import_enumerate_conversations_activity,
                    EnumerateConversationsInput(job_id=input.job_id, cursor=cursor),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RETRY_POLICY,
                )
                cursor = page.next_cursor
                pages_processed += 1

                # Publish a running total as conversations are enumerated so the UI can render
                # "processed / total".
                if page.conversation_ids:
                    await workflow.execute_activity(
                        intercom_import_update_job_progress_activity,
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            total_delta=len(page.conversation_ids),
                            export_cursor=cursor,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RETRY_POLICY,
                    )

                ids = page.conversation_ids
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
                                wf_input=IntercomImportBatchWorkflowInput(
                                    job_id=input.job_id,
                                    team_id=input.team_id,
                                    conversation_ids=batch,
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
                    total_imported += window_imported
                    total_skipped += window_skipped
                    total_failed += window_failed

                    await workflow.execute_activity(
                        intercom_import_update_job_progress_activity,
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            processed_delta=sum(len(batch) for batch in window),
                            imported_delta=window_imported,
                            skipped_delta=window_skipped,
                            failed_delta=window_failed,
                            export_cursor=cursor,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RETRY_POLICY,
                    )

                if cursor is None:
                    break

                if pages_processed >= CONTINUE_AS_NEW_AFTER_PAGES:
                    workflow.continue_as_new(
                        IntercomImportCoordinatorInput(
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
                        )
                    )

            await workflow.execute_activity(
                intercom_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=IntercomImportJob.Status.COMPLETED),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            return IntercomImportCoordinatorOutput(imported=total_imported, skipped=total_skipped, failed=total_failed)
        except asyncio.CancelledError:
            # Cancellation subclasses BaseException, so `except Exception` can't see it. Record a
            # terminal state so the settings UI doesn't poll "Syncing" forever.
            workflow.logger.warning(
                "intercom_import_coordinator_cancelled",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                intercom_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=IntercomImportJob.Status.FAILED,
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
                "intercom_import_coordinator_failed",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                intercom_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=IntercomImportJob.Status.FAILED,
                    latest_error=IMPORT_FAILED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise


@workflow.defn(name="intercom-import-batch")
class IntercomImportBatchWorkflow:
    @workflow.run
    async def run(self, input: IntercomImportBatchWorkflowInput) -> IntercomImportCoordinatorOutput:
        result = await workflow.execute_activity(
            intercom_import_batch_activity,
            ImportBatchInput(
                job_id=input.job_id,
                team_id=input.team_id,
                conversation_ids=input.conversation_ids,
                default_email_channel_id=input.default_email_channel_id,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RETRY_POLICY,
        )
        return IntercomImportCoordinatorOutput(imported=result.imported, skipped=result.skipped, failed=result.failed)
