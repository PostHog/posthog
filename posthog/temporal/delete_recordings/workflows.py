import json
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
    DeleteFailure,
    DeleteSuccess,
    DeletionCertificate,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)


async def _batch_delete(session_ids: list[str], team_id: int, batch_size: int, dry_run: bool) -> list[BulkDeleteResult]:
    results: list[BulkDeleteResult] = []
    if not dry_run:
        for batch in batched(session_ids, batch_size):
            result = await workflow.execute_activity(
                bulk_delete_recordings,
                BulkDeleteInput(team_id=team_id, session_ids=list(batch)),
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=timedelta(hours=3),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
            )
            results.append(result)
    return results


MAX_CERTIFICATE_ENTRIES = 10_000


def _build_certificate(
    workflow_type: Literal["person", "team", "query"],
    workflow_id: str,
    team_id: int,
    started_at: datetime,
    total_recordings_found: int,
    results: list[BulkDeleteResult],
    dry_run: bool = False,
    distinct_ids: list[str] | None = None,
    query: str | None = None,
) -> DeletionCertificate:
    """Build a deletion certificate from the batch results."""
    completed_at = datetime.now(UTC)

    deleted_recordings: list[DeleteSuccess] = []
    all_failed: list[DeleteFailure] = []

    for result in results:
        for session_id in result.deleted:
            deleted_recordings.append(DeleteSuccess(session_id=session_id, deleted_at=completed_at))
        all_failed.extend(result.failed)

    return DeletionCertificate(
        workflow_type=workflow_type,
        workflow_id=workflow_id,
        team_id=team_id,
        started_at=started_at,
        completed_at=completed_at,
        dry_run=dry_run,
        distinct_ids=distinct_ids,
        query=query,
        total_recordings_found=total_recordings_found,
        total_deleted=len(deleted_recordings),
        total_failed=len(all_failed),
        failed=all_failed,
        deleted_recordings=deleted_recordings[:MAX_CERTIFICATE_ENTRIES],
    )


@workflow.defn(name="delete-recordings-with-person")
class DeleteRecordingsWithPersonWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithPersonInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return RecordingsWithPersonInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithPersonInput) -> DeletionCertificate:
        started_at = datetime.now(UTC)

        session_ids = await workflow.execute_activity(
            load_recordings_with_person,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        results = await _batch_delete(session_ids, input.team_id, input.batch_size, input.dry_run)

        return _build_certificate(
            workflow_type="person",
            workflow_id=workflow.info().workflow_id,
            team_id=input.team_id,
            started_at=started_at,
            total_recordings_found=len(session_ids),
            results=results,
            dry_run=input.dry_run,
            distinct_ids=input.distinct_ids,
        )


@workflow.defn(name="delete-recordings-with-team")
class DeleteRecordingsWithTeamWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithTeamInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return RecordingsWithTeamInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithTeamInput) -> DeletionCertificate:
        started_at = datetime.now(UTC)

        session_ids = await workflow.execute_activity(
            load_recordings_with_team_id,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        results = await _batch_delete(session_ids, input.team_id, input.batch_size, input.dry_run)

        return _build_certificate(
            workflow_type="team",
            workflow_id=workflow.info().workflow_id,
            team_id=input.team_id,
            started_at=started_at,
            total_recordings_found=len(session_ids),
            results=results,
            dry_run=input.dry_run,
        )


@workflow.defn(name="delete-recordings-with-query")
class DeleteRecordingsWithQueryWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithQueryInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return RecordingsWithQueryInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithQueryInput) -> DeletionCertificate:
        started_at = datetime.now(UTC)

        session_ids = await workflow.execute_activity(
            load_recordings_with_query,
            input,
            start_to_close_timeout=timedelta(hours=2),
            schedule_to_close_timeout=timedelta(hours=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=2),
            ),
        )

        results = await _batch_delete(session_ids, input.team_id, input.batch_size, input.dry_run)

        return _build_certificate(
            workflow_type="query",
            workflow_id=workflow.info().workflow_id,
            team_id=input.team_id,
            started_at=started_at,
            total_recordings_found=len(session_ids),
            results=results,
            dry_run=input.dry_run,
            query=input.query,
        )


@workflow.defn(name="purge-deleted-recording-metadata")
class PurgeDeletedRecordingMetadataWorkflow(PostHogWorkflow):
    """Nightly workflow to purge metadata from ClickHouse for deleted recordings.

    After recordings are deleted, the metadata remain in ClickHouse with is_deleted=1.
    This workflow runs nightly to clean up that metadata after a grace period has passed.
    """

    @staticmethod
    def parse_inputs(input: list[str]) -> PurgeDeletedMetadataInput:
        """Parse input from the management command CLI."""
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
