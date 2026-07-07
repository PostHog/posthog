"""Temporal workflows for Zendesk historical ticket import."""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from products.conversations.backend.models.zendesk_import_job import ZendeskImportJob
    from products.conversations.backend.temporal.zendesk_import.activities import (
        EnumerateTicketsInput,
        ImportBatchInput,
        UpdateJobProgressInput,
        UpdateJobStatusInput,
        zendesk_import_batch_activity,
        zendesk_import_enumerate_tickets_activity,
        zendesk_import_update_job_progress_activity,
        zendesk_import_update_job_status_activity,
    )
    from products.conversations.backend.temporal.zendesk_import.constants import (
        BATCH_SIZE,
        BATCH_WORKFLOW_ID_PREFIX,
        CONTINUE_AS_NEW_AFTER_PAGES,
        MAX_CONCURRENT_BATCH_WORKFLOWS,
        WORKFLOW_ID_PREFIX,
    )


IMPORT_FAILED_MESSAGE = "The import failed. Please try again or contact support if it persists."
IMPORT_CANCELLED_MESSAGE = "The import was cancelled."


@dataclass
class ZendeskImportCoordinatorInput:
    job_id: str
    team_id: int
    cursor: str | None = None
    pages_processed: int = 0
    # Cumulative pages completed in prior continue-as-new generations. Child workflow IDs are
    # built from the *absolute* page index (pages_offset + pages_processed); without this the
    # per-run pages_processed resets to 0 each generation, regenerating child IDs that collide
    # with the previous generation's already-completed children (ALLOW_DUPLICATE_FAILED_ONLY ->
    # WorkflowAlreadyStartedError -> zero imports past the first CAN boundary).
    pages_offset: int = 0
    dry_run: bool = False
    # Cap total tickets enumerated for import (ops/testing). None = no cap. Carried across
    # continue-as-new as the *remaining* budget so the cap holds over the whole run.
    max_tickets: int | None = None
    # Fallback EmailChannel (UUID str) for tickets whose Zendesk recipient doesn't match a
    # configured support address. None = leave email_config null in those cases.
    default_email_channel_id: str | None = None


@dataclass
class ZendeskImportCoordinatorOutput:
    imported: int
    skipped: int
    failed: int


@dataclass
class ZendeskImportBatchWorkflowInput:
    job_id: str
    team_id: int
    ticket_ids: list[int]
    dry_run: bool = False
    default_email_channel_id: str | None = None


RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))


@workflow.defn(name="zendesk-import-coordinator")
class ZendeskImportCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ZendeskImportCoordinatorInput:
        if not inputs:
            raise ValueError("ZendeskImportCoordinatorWorkflow requires input")
        loaded = json.loads(inputs[0])
        return ZendeskImportCoordinatorInput(**loaded)

    async def _run_batch_child(
        self, *, child_id: str, wf_input: ZendeskImportBatchWorkflowInput
    ) -> ZendeskImportCoordinatorOutput:
        try:
            return await workflow.execute_child_workflow(
                ZendeskImportBatchWorkflow.run,
                wf_input,
                id=child_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            )
        except WorkflowAlreadyStartedError:
            # workflow.logger is a stdlib LoggerAdapter — structlog-style kwargs raise TypeError.
            workflow.logger.info("zendesk_import_batch_already_running", extra={"child_id": child_id})
            return ZendeskImportCoordinatorOutput(imported=0, skipped=0, failed=0)

    @workflow.run
    async def run(self, input: ZendeskImportCoordinatorInput) -> ZendeskImportCoordinatorOutput:
        if input.pages_processed == 0:
            await workflow.execute_activity(
                zendesk_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=ZendeskImportJob.Status.RUNNING),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )

        total_imported = 0
        total_skipped = 0
        total_failed = 0
        cursor = input.cursor
        pages_processed = input.pages_processed
        selected = 0  # tickets picked for import this run (against max_tickets budget)

        try:
            while True:
                page = await workflow.execute_activity(
                    zendesk_import_enumerate_tickets_activity,
                    EnumerateTicketsInput(job_id=input.job_id, cursor=cursor),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RETRY_POLICY,
                )
                cursor = page.next_cursor
                pages_processed += 1

                ticket_ids = page.ticket_ids
                reached_cap = False
                if input.max_tickets is not None:
                    remaining = input.max_tickets - selected
                    if remaining <= 0:
                        break
                    if len(ticket_ids) >= remaining:
                        ticket_ids = ticket_ids[:remaining]
                        reached_cap = True
                selected += len(ticket_ids)
                page.ticket_ids = ticket_ids

                # Publish a running total as tickets are enumerated (cursor export has no
                # upfront count) so the UI can render "processed / total".
                if page.ticket_ids:
                    await workflow.execute_activity(
                        zendesk_import_update_job_progress_activity,
                        UpdateJobProgressInput(
                            job_id=input.job_id,
                            total_delta=len(page.ticket_ids),
                            export_cursor=cursor,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RETRY_POLICY,
                    )

                batches = [page.ticket_ids[i : i + BATCH_SIZE] for i in range(0, len(page.ticket_ids), BATCH_SIZE)]

                # Fan out batches with bounded concurrency, checkpointing progress per window.
                for window_start in range(0, len(batches), MAX_CONCURRENT_BATCH_WORKFLOWS):
                    window = batches[window_start : window_start + MAX_CONCURRENT_BATCH_WORKFLOWS]
                    results = await asyncio.gather(
                        *[
                            self._run_batch_child(
                                child_id=(
                                    f"{BATCH_WORKFLOW_ID_PREFIX}-{input.job_id}"
                                    f"-{input.pages_offset + pages_processed}-{window_start + offset}"
                                ),
                                wf_input=ZendeskImportBatchWorkflowInput(
                                    job_id=input.job_id,
                                    team_id=input.team_id,
                                    ticket_ids=batch,
                                    dry_run=input.dry_run,
                                    default_email_channel_id=input.default_email_channel_id,
                                ),
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
                        zendesk_import_update_job_progress_activity,
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
                        ZendeskImportCoordinatorInput(
                            job_id=input.job_id,
                            team_id=input.team_id,
                            cursor=cursor,
                            pages_processed=0,
                            pages_offset=input.pages_offset + pages_processed,
                            dry_run=input.dry_run,
                            max_tickets=None if input.max_tickets is None else input.max_tickets - selected,
                            default_email_channel_id=input.default_email_channel_id,
                        )
                    )

            await workflow.execute_activity(
                zendesk_import_update_job_status_activity,
                UpdateJobStatusInput(job_id=input.job_id, status=ZendeskImportJob.Status.COMPLETED),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            return ZendeskImportCoordinatorOutput(
                imported=total_imported,
                skipped=total_skipped,
                failed=total_failed,
            )
        except asyncio.CancelledError:
            # Cancellation (admin cancels from the Temporal UI/CLI, handle.cancel(), a future
            # "cancel import" action) is delivered as asyncio.CancelledError, which subclasses
            # BaseException — the `except Exception` below can't see it. Without recording a
            # terminal state here the ZendeskImportJob row stays stuck at RUNNING forever, and the
            # settings UI polls "Syncing" indefinitely (the migrate_zendesk_tickets --force flag
            # exists to clean up exactly this). Scheduling a cleanup activity after cancel is the
            # supported Temporal pattern; the request is state-once so this await isn't re-cancelled.
            workflow.logger.warning(
                "zendesk_import_coordinator_cancelled",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                zendesk_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=ZendeskImportJob.Status.FAILED,
                    latest_error=IMPORT_CANCELLED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise
        except Exception:
            # Raw exception strings can carry internal hostnames, query details, or
            # secrets from failing requests. Log the full error server-side and persist
            # only a generic message for the admin-facing UI.
            workflow.logger.exception(
                "zendesk_import_coordinator_failed",
                extra={"job_id": input.job_id, "team_id": input.team_id},
            )
            await workflow.execute_activity(
                zendesk_import_update_job_status_activity,
                UpdateJobStatusInput(
                    job_id=input.job_id,
                    status=ZendeskImportJob.Status.FAILED,
                    latest_error=IMPORT_FAILED_MESSAGE,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            raise


@workflow.defn(name="zendesk-import-batch")
class ZendeskImportBatchWorkflow:
    @workflow.run
    async def run(self, input: ZendeskImportBatchWorkflowInput) -> ZendeskImportCoordinatorOutput:
        result = await workflow.execute_activity(
            zendesk_import_batch_activity,
            ImportBatchInput(
                job_id=input.job_id,
                team_id=input.team_id,
                ticket_ids=input.ticket_ids,
                dry_run=input.dry_run,
                default_email_channel_id=input.default_email_channel_id,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RETRY_POLICY,
        )
        return ZendeskImportCoordinatorOutput(
            imported=result.imported,
            skipped=result.skipped,
            failed=result.failed,
        )


def coordinator_workflow_id(team_id: int) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{team_id}"
