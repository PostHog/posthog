import json
import asyncio
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Literal

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_recordings.activities import (
    bulk_delete_recordings,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    purge_deleted_metadata,
)
from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeletionCertificate,
    DeletionConfig,
    DeletionProgress,
    LoadRecordingsPage,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithSessionIdsInput,
    RecordingsWithTeamInput,
)


async def _delete_page(
    page: LoadRecordingsPage,
    team_id: int,
    config: DeletionConfig,
    progress: DeletionProgress,
) -> None:
    """Batch-delete a page of session IDs and update progress."""
    if page.session_ids:
        batch_start = datetime.now(UTC)
        progress.total_found += len(page.session_ids)

        for batch in batched(page.session_ids, config.batch_size):
            result: BulkDeleteResult = await workflow.execute_activity(
                bulk_delete_recordings,
                BulkDeleteInput(team_id=team_id, session_ids=list(batch), dry_run=config.dry_run),
                start_to_close_timeout=timedelta(minutes=2),
                schedule_to_close_timeout=timedelta(minutes=30),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
            )
            progress.total_deleted += len(result.deleted)
            progress.total_failed += len(result.failed)
            progress.failed.extend(result.failed)

        if config.max_deletions_per_second > 0:
            elapsed = (datetime.now(UTC) - batch_start).total_seconds()
            target = len(page.session_ids) / config.max_deletions_per_second
            if elapsed < target:
                await asyncio.sleep(target - elapsed)

    progress.cursor = page.next_cursor


def _build_certificate(
    workflow_type: Literal["person", "team", "query", "session_ids"],
    workflow_id: str,
    team_id: int,
    progress: DeletionProgress,
    config: DeletionConfig,
    distinct_ids: list[str] | None = None,
    query: str | None = None,
    source_filename: str | None = None,
) -> DeletionCertificate:
    return DeletionCertificate(
        workflow_type=workflow_type,
        workflow_id=workflow_id,
        team_id=team_id,
        started_at=progress.started_at or datetime.now(UTC),
        completed_at=datetime.now(UTC),
        dry_run=config.dry_run,
        reason=config.reason,
        distinct_ids=distinct_ids,
        query=query,
        source_filename=source_filename,
        total_recordings_found=progress.total_found,
        total_deleted=progress.total_deleted,
        total_failed=progress.total_failed,
        failed=progress.failed,
    )


@workflow.defn(name="delete-recordings-with-person")
class DeleteRecordingsWithPersonWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithPersonInput:
        loaded = json.loads(input[0])
        return RecordingsWithPersonInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithPersonInput) -> DeletionCertificate:
        progress = input.progress or DeletionProgress(started_at=datetime.now(UTC))

        while True:
            page: LoadRecordingsPage = await workflow.execute_activity(
                load_recordings_with_person,
                RecordingsWithPersonInput(
                    distinct_ids=input.distinct_ids,
                    team_id=input.team_id,
                    cursor=progress.cursor,
                    page_size=input.page_size,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                schedule_to_close_timeout=timedelta(minutes=30),
                retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
            )

            await _delete_page(page, input.team_id, input.config, progress)

            if page.next_cursor is None:
                return _build_certificate(
                    "person",
                    workflow.info().workflow_id,
                    input.team_id,
                    progress,
                    input.config,
                    distinct_ids=input.distinct_ids,
                )

            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    RecordingsWithPersonInput(
                        distinct_ids=input.distinct_ids,
                        team_id=input.team_id,
                        config=input.config,
                        page_size=input.page_size,
                        progress=progress,
                    )
                )


@workflow.defn(name="delete-recordings-with-team")
class DeleteRecordingsWithTeamWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithTeamInput:
        loaded = json.loads(input[0])
        return RecordingsWithTeamInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithTeamInput) -> DeletionCertificate:
        progress = input.progress or DeletionProgress(started_at=datetime.now(UTC))

        while True:
            page: LoadRecordingsPage = await workflow.execute_activity(
                load_recordings_with_team_id,
                RecordingsWithTeamInput(
                    team_id=input.team_id,
                    cursor=progress.cursor,
                    page_size=input.page_size,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                schedule_to_close_timeout=timedelta(minutes=30),
                retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
            )

            await _delete_page(page, input.team_id, input.config, progress)

            if page.next_cursor is None:
                return _build_certificate(
                    "team",
                    workflow.info().workflow_id,
                    input.team_id,
                    progress,
                    input.config,
                )

            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    RecordingsWithTeamInput(
                        team_id=input.team_id,
                        config=input.config,
                        page_size=input.page_size,
                        progress=progress,
                    )
                )


@workflow.defn(name="delete-recordings-with-query")
class DeleteRecordingsWithQueryWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithQueryInput:
        loaded = json.loads(input[0])
        return RecordingsWithQueryInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithQueryInput) -> DeletionCertificate:
        progress = input.progress or DeletionProgress(started_at=datetime.now(UTC))

        while True:
            page: LoadRecordingsPage = await workflow.execute_activity(
                load_recordings_with_query,
                RecordingsWithQueryInput(
                    query=input.query,
                    team_id=input.team_id,
                    query_limit=input.query_limit,
                    cursor=progress.cursor,
                ),
                start_to_close_timeout=timedelta(minutes=15),
                schedule_to_close_timeout=timedelta(hours=1),
                retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=2)),
            )

            await _delete_page(page, input.team_id, input.config, progress)

            if page.next_cursor is None:
                return _build_certificate(
                    "query",
                    workflow.info().workflow_id,
                    input.team_id,
                    progress,
                    input.config,
                    query=input.query,
                )

            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    RecordingsWithQueryInput(
                        query=input.query,
                        team_id=input.team_id,
                        config=input.config,
                        query_limit=input.query_limit,
                        progress=progress,
                    )
                )


@workflow.defn(name="delete-recordings-with-session-ids")
class DeleteRecordingsWithSessionIdsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithSessionIdsInput:
        loaded = json.loads(input[0])
        return RecordingsWithSessionIdsInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithSessionIdsInput) -> DeletionCertificate:
        progress = input.progress or DeletionProgress(started_at=datetime.now(UTC))

        offset = progress.total_found
        while offset < len(input.session_ids):
            chunk = input.session_ids[offset : offset + 10_000]
            page = LoadRecordingsPage(session_ids=chunk)
            await _delete_page(page, input.team_id, input.config, progress)
            offset = progress.total_found

            if offset < len(input.session_ids) and workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    RecordingsWithSessionIdsInput(
                        session_ids=input.session_ids,
                        team_id=input.team_id,
                        config=input.config,
                        source_filename=input.source_filename,
                        progress=progress,
                    )
                )

        return _build_certificate(
            "session_ids",
            workflow.info().workflow_id,
            input.team_id,
            progress,
            input.config,
            source_filename=input.source_filename,
        )


@workflow.defn(name="purge-deleted-recording-metadata")
class PurgeDeletedRecordingMetadataWorkflow(PostHogWorkflow):
    """Nightly workflow to purge metadata from ClickHouse for deleted recordings.

    After recordings are deleted, the metadata remain in ClickHouse with is_deleted=1.
    This workflow runs nightly to clean up that metadata after a grace period has passed.
    """

    @staticmethod
    def parse_inputs(input: list[str]) -> PurgeDeletedMetadataInput:
        loaded = json.loads(input[0])
        return PurgeDeletedMetadataInput(**loaded)

    @workflow.run
    async def run(self, input: PurgeDeletedMetadataInput) -> PurgeDeletedMetadataResult:
        return await workflow.execute_activity(
            purge_deleted_metadata,
            input,
            start_to_close_timeout=timedelta(hours=2),
            schedule_to_close_timeout=timedelta(hours=4),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(minutes=5),
            ),
        )
