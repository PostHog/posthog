import json
import typing
import datetime as dt
import dataclasses

import temporalio.common
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.sync_person_distinct_ids.activities import (
    FindOrphanedPersonsInputs,
    LookupPgDistinctIdsInputs,
    MarkChOnlyOrphansDeletedInputs,
    SyncDistinctIdsToChInputs,
    find_orphaned_persons,
    lookup_pg_distinct_ids,
    mark_ch_only_orphans_deleted,
    sync_distinct_ids_to_ch,
)


@dataclasses.dataclass
class SyncPersonDistinctIdsWorkflowInputs:
    """Inputs for the SyncPersonDistinctIds workflow.

    Attributes:
        team_id: Team ID to process orphaned persons for.
        batch_size: Number of persons to process per activity batch.
        dry_run: If True, only log what would be synced without making changes.
        delete_ch_only_orphans: If True, mark CH-only orphans as deleted.
        categorize_orphans: If True, run extra query to distinguish truly orphaned vs CH-only.
        limit: Max persons to process (for testing).
        person_ids: Specific person UUIDs to process (for testing).
    """

    team_id: int
    batch_size: int = 100
    dry_run: bool = True
    delete_ch_only_orphans: bool = False
    categorize_orphans: bool = False
    limit: int | None = None
    person_ids: list[str] | None = None

    def __post_init__(self):
        if self.delete_ch_only_orphans and not self.categorize_orphans:
            raise ValueError(
                "delete_ch_only_orphans=True requires categorize_orphans=True. "
                "Without categorization, we cannot distinguish CH-only orphans from "
                "truly orphaned persons (in PG but without DIDs)."
            )

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
            "dry_run": self.dry_run,
            "delete_ch_only_orphans": self.delete_ch_only_orphans,
            "categorize_orphans": self.categorize_orphans,
            "limit": self.limit,
            "person_ids_count": len(self.person_ids) if self.person_ids else 0,
        }


@dataclasses.dataclass
class SyncPersonDistinctIdsWorkflowResult:
    """Result of the SyncPersonDistinctIds workflow.

    Attributes:
        team_id: The team that was processed.
        total_orphaned_persons: Total count of orphaned persons found in ClickHouse.
        persons_with_pg_distinct_ids: Count of persons that have distinct IDs in PostgreSQL (fixable).
        distinct_ids_synced: Count of distinct IDs that were synced to ClickHouse.
        persons_without_pg_data: Count of persons without DIDs in PG (truly orphaned + CH-only).
        persons_truly_orphaned: Count of persons in PG but without DIDs (only if categorize_orphans=True).
        persons_ch_only: Count of persons not in PG at all (only if categorize_orphans=True).
        persons_marked_deleted: Count of persons marked as deleted in CH.
        dry_run: Whether this was a dry run.
    """

    team_id: int
    total_orphaned_persons: int
    persons_with_pg_distinct_ids: int
    distinct_ids_synced: int
    persons_without_pg_data: int
    persons_truly_orphaned: int
    persons_ch_only: int
    persons_marked_deleted: int
    dry_run: bool


@temporalio.workflow.defn(name="sync-person-distinct-ids")
class SyncPersonDistinctIdsWorkflow(PostHogWorkflow):
    """Workflow to sync missing person distinct IDs from PostgreSQL to ClickHouse.

    This workflow:
    1. Finds orphaned persons in ClickHouse (persons without distinct IDs)
    2. Looks up their distinct IDs in PostgreSQL
    3. Syncs the missing distinct IDs to ClickHouse via Kafka
    4. Optionally marks CH-only orphans (no PG data) as deleted
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncPersonDistinctIdsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncPersonDistinctIdsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SyncPersonDistinctIdsWorkflowInputs) -> SyncPersonDistinctIdsWorkflowResult:
        """Execute the sync workflow."""
        persons_with_pg_ids = 0
        distinct_ids_synced = 0
        persons_without_pg_data = 0
        persons_truly_orphaned = 0
        persons_ch_only = 0
        persons_marked_deleted = 0

        retry_policy = temporalio.common.RetryPolicy(
            initial_interval=dt.timedelta(seconds=10),
            maximum_interval=dt.timedelta(minutes=2),
            maximum_attempts=5,
        )

        # Step 1: Find orphaned persons in ClickHouse
        # This also fetches versions needed for deletion (ClickHouse needs version+1 to override)
        find_result = await temporalio.workflow.execute_activity(
            find_orphaned_persons,
            FindOrphanedPersonsInputs(
                team_id=inputs.team_id,
                limit=inputs.limit,
                person_ids=inputs.person_ids,  # Filter to specific persons if provided
            ),
            start_to_close_timeout=dt.timedelta(minutes=10),
            heartbeat_timeout=dt.timedelta(seconds=60),
            retry_policy=retry_policy,
        )
        person_uuids = [p.person_id for p in find_result.orphaned_persons]
        person_versions = {p.person_id: p.version for p in find_result.orphaned_persons}

        total_orphaned = len(person_uuids)

        # Step 2: Process in batches (PG lookups and CH writes are the expensive parts)
        for i in range(0, len(person_uuids), inputs.batch_size):
            batch_uuids = person_uuids[i : i + inputs.batch_size]

            # Look up distinct IDs in PostgreSQL
            lookup_result = await temporalio.workflow.execute_activity(
                lookup_pg_distinct_ids,
                LookupPgDistinctIdsInputs(
                    team_id=inputs.team_id,
                    person_uuids=batch_uuids,
                    categorize_not_found=inputs.categorize_orphans,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                heartbeat_timeout=dt.timedelta(seconds=30),
                retry_policy=retry_policy,
            )

            persons_with_pg_ids += len(lookup_result.mappings)
            persons_without_pg_data += len(lookup_result.persons_not_found)
            persons_truly_orphaned += len(lookup_result.persons_truly_orphaned)
            persons_ch_only += len(lookup_result.persons_ch_only)

            # Sync distinct IDs to ClickHouse
            if lookup_result.mappings:
                sync_result = await temporalio.workflow.execute_activity(
                    sync_distinct_ids_to_ch,
                    SyncDistinctIdsToChInputs(
                        team_id=inputs.team_id,
                        mappings=lookup_result.mappings,
                        dry_run=inputs.dry_run,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(seconds=60),
                    retry_policy=retry_policy,
                )
                distinct_ids_synced += sync_result.distinct_ids_synced

            # Mark CH-only orphans as deleted (if enabled)
            # Validation ensures categorize_orphans=True when delete_ch_only_orphans=True
            if inputs.delete_ch_only_orphans and lookup_result.persons_ch_only:
                # Build version map for persons to delete
                delete_versions = {uuid: person_versions.get(uuid, 0) for uuid in lookup_result.persons_ch_only}
                delete_result = await temporalio.workflow.execute_activity(
                    mark_ch_only_orphans_deleted,
                    MarkChOnlyOrphansDeletedInputs(
                        team_id=inputs.team_id,
                        person_versions=delete_versions,
                        dry_run=inputs.dry_run,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(seconds=60),
                    retry_policy=retry_policy,
                )
                persons_marked_deleted += delete_result.persons_marked_deleted

        return SyncPersonDistinctIdsWorkflowResult(
            team_id=inputs.team_id,
            total_orphaned_persons=total_orphaned,
            persons_with_pg_distinct_ids=persons_with_pg_ids,
            distinct_ids_synced=distinct_ids_synced,
            persons_without_pg_data=persons_without_pg_data,
            persons_truly_orphaned=persons_truly_orphaned,
            persons_ch_only=persons_ch_only,
            persons_marked_deleted=persons_marked_deleted,
            dry_run=inputs.dry_run,
        )
