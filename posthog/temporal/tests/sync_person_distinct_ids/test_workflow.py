"""Integration tests for SyncPersonDistinctIdsWorkflow with real database operations."""

import uuid

import pytest

import temporalio.worker
from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models.person import Person, PersonDistinctId
from posthog.person_db_router import PERSONS_DB_FOR_WRITE
from posthog.temporal.sync_person_distinct_ids.activities import (
    find_orphaned_persons,
    lookup_pg_distinct_ids,
    mark_ch_only_orphans_deleted,
    sync_distinct_ids_to_ch,
)
from posthog.temporal.sync_person_distinct_ids.workflow import (
    SyncPersonDistinctIdsWorkflow,
    SyncPersonDistinctIdsWorkflowInputs,
)
from posthog.temporal.tests.sync_person_distinct_ids.conftest import (
    cleanup_ch_test_data,
    get_ch_person,
    get_orphaned_person_count,
    insert_person_to_ch,
    insert_persons_to_ch_batch,
)


@pytest.mark.django_db(transaction=True)
class TestSyncPersonDistinctIdsWorkflow:
    """Test the full workflow with real activities and database operations."""

    FIXABLE_COUNT = 40
    TRULY_ORPHANED_COUNT = 30
    CH_ONLY_COUNT = 30
    BATCH_SIZE = 30  # Small batch size to ensure multiple batches (4 batches for 100 items)

    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix):
        self.team = team
        self.prefix = test_prefix
        self.created_person_uuids: list[str] = []
        self.created_distinct_ids: list[str] = []
        self.fixable_uuids: list[str] = []
        self.truly_orphaned_uuids: list[str] = []
        self.ch_only_uuids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, self.created_distinct_ids)
        PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, distinct_id__startswith=self.prefix
        ).delete()
        Person.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, uuid__in=self.created_person_uuids
        ).delete()

    async def _create_test_data(self):
        """Create 100 orphaned persons across all three categories."""
        assert get_orphaned_person_count(self.team.id) == 0

        # Generate all UUIDs first
        for i in range(self.FIXABLE_COUNT):
            person_uuid = str(uuid.uuid4())
            distinct_id = f"{self.prefix}-fixable-{i}"
            self.fixable_uuids.append(person_uuid)
            self.created_person_uuids.append(person_uuid)
            self.created_distinct_ids.append(distinct_id)

        for _ in range(self.TRULY_ORPHANED_COUNT):
            person_uuid = str(uuid.uuid4())
            self.truly_orphaned_uuids.append(person_uuid)
            self.created_person_uuids.append(person_uuid)

        for _ in range(self.CH_ONLY_COUNT):
            person_uuid = str(uuid.uuid4())
            self.ch_only_uuids.append(person_uuid)
            self.created_person_uuids.append(person_uuid)

        # Batch insert all persons to ClickHouse
        insert_persons_to_ch_batch(self.team.id, self.created_person_uuids, version=0)

        # Create PG data for fixable and truly orphaned
        @sync_to_async
        def create_pg_data():
            # Fixable: Person in PG with DID - use bulk_create for efficiency
            fixable_persons = [Person(team=self.team, uuid=person_uuid) for person_uuid in self.fixable_uuids]
            created_persons = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).bulk_create(fixable_persons)

            # Create distinct IDs for fixable persons
            distinct_id_objects = []
            for i, person in enumerate(created_persons):
                distinct_id = f"{self.prefix}-fixable-{i}"
                distinct_id_objects.append(
                    PersonDistinctId(team=self.team, person=person, distinct_id=distinct_id, version=0)
                )
            PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).bulk_create(distinct_id_objects)

            # Truly orphaned: Person in PG, no DID - use bulk_create
            truly_orphaned_persons = [
                Person(team=self.team, uuid=person_uuid) for person_uuid in self.truly_orphaned_uuids
            ]
            Person.objects.db_manager(PERSONS_DB_FOR_WRITE).bulk_create(truly_orphaned_persons)

        await create_pg_data()

        total_orphans = self.FIXABLE_COUNT + self.TRULY_ORPHANED_COUNT + self.CH_ONLY_COUNT
        assert get_orphaned_person_count(self.team.id) == total_orphans

    @pytest.mark.asyncio
    async def test_workflow_dry_run(self):
        """Test workflow dry run mode - reports counts but makes no changes."""
        await self._create_test_data()

        total_orphans = self.FIXABLE_COUNT + self.TRULY_ORPHANED_COUNT + self.CH_ONLY_COUNT

        task_queue_name = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue_name,
                workflows=[SyncPersonDistinctIdsWorkflow],
                activities=[
                    find_orphaned_persons,
                    lookup_pg_distinct_ids,
                    sync_distinct_ids_to_ch,
                    mark_ch_only_orphans_deleted,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    SyncPersonDistinctIdsWorkflow.run,
                    SyncPersonDistinctIdsWorkflowInputs(
                        team_id=self.team.id,
                        batch_size=self.BATCH_SIZE,
                        dry_run=True,
                        categorize_orphans=True,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

        # Verify workflow result
        assert result.team_id == self.team.id
        assert result.dry_run is True
        assert result.total_orphaned_persons == total_orphans
        assert result.persons_with_pg_distinct_ids == self.FIXABLE_COUNT
        assert result.distinct_ids_synced == self.FIXABLE_COUNT
        assert result.persons_truly_orphaned == self.TRULY_ORPHANED_COUNT
        assert result.persons_ch_only == self.CH_ONLY_COUNT
        assert result.persons_marked_deleted == 0  # dry_run + delete not enabled

        # Verify no changes were made to the database
        assert get_orphaned_person_count(self.team.id) == total_orphans

    @pytest.mark.asyncio
    async def test_workflow_sync_only(self):
        """Test workflow sync-only mode - syncs fixable orphans, doesn't delete CH-only."""
        await self._create_test_data()

        task_queue_name = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue_name,
                workflows=[SyncPersonDistinctIdsWorkflow],
                activities=[
                    find_orphaned_persons,
                    lookup_pg_distinct_ids,
                    sync_distinct_ids_to_ch,
                    mark_ch_only_orphans_deleted,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    SyncPersonDistinctIdsWorkflow.run,
                    SyncPersonDistinctIdsWorkflowInputs(
                        team_id=self.team.id,
                        batch_size=self.BATCH_SIZE,
                        dry_run=False,
                        delete_ch_only_orphans=False,
                        categorize_orphans=True,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

        # Verify workflow result
        assert result.dry_run is False
        assert result.persons_with_pg_distinct_ids == self.FIXABLE_COUNT
        assert result.distinct_ids_synced == self.FIXABLE_COUNT
        assert result.persons_marked_deleted == 0

        # Verify fixable orphans are resolved, truly orphaned + CH-only remain
        remaining_orphans = self.TRULY_ORPHANED_COUNT + self.CH_ONLY_COUNT
        assert get_orphaned_person_count(self.team.id) == remaining_orphans

    @pytest.mark.asyncio
    async def test_workflow_sync_and_delete(self):
        """Test workflow sync + delete mode - syncs fixable, deletes CH-only."""
        await self._create_test_data()

        task_queue_name = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue_name,
                workflows=[SyncPersonDistinctIdsWorkflow],
                activities=[
                    find_orphaned_persons,
                    lookup_pg_distinct_ids,
                    sync_distinct_ids_to_ch,
                    mark_ch_only_orphans_deleted,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    SyncPersonDistinctIdsWorkflow.run,
                    SyncPersonDistinctIdsWorkflowInputs(
                        team_id=self.team.id,
                        batch_size=self.BATCH_SIZE,
                        dry_run=False,
                        delete_ch_only_orphans=True,
                        categorize_orphans=True,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

        # Verify workflow result
        assert result.dry_run is False
        assert result.persons_with_pg_distinct_ids == self.FIXABLE_COUNT
        assert result.distinct_ids_synced == self.FIXABLE_COUNT
        assert result.persons_ch_only == self.CH_ONLY_COUNT
        assert result.persons_marked_deleted == self.CH_ONLY_COUNT

        # Verify only truly orphaned remain (fixable synced, CH-only deleted)
        assert get_orphaned_person_count(self.team.id) == self.TRULY_ORPHANED_COUNT

    @pytest.mark.asyncio
    async def test_workflow_deletes_with_correct_versions(self):
        """Test that workflow correctly increments versions when marking persons as deleted.

        This is important because ClickHouse's ReplacingMergeTree uses the version
        column to determine which record to keep. If we use a version lower than
        the current one, the deletion will be ignored.
        """
        # Create 3 CH-only orphans with different versions
        versions = [1, 1234, 123456789]
        person_uuids = []

        for version in versions:
            person_uuid = str(uuid.uuid4())
            person_uuids.append(person_uuid)
            self.created_person_uuids.append(person_uuid)
            insert_person_to_ch(self.team.id, person_uuid, version=version)

        # Verify all persons exist and are not deleted
        for i, person_uuid in enumerate(person_uuids):
            ch_person = get_ch_person(self.team.id, person_uuid)
            assert ch_person is not None
            assert ch_person["is_deleted"] == 0
            assert ch_person["version"] == versions[i]

        task_queue_name = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue_name,
                workflows=[SyncPersonDistinctIdsWorkflow],
                activities=[
                    find_orphaned_persons,
                    lookup_pg_distinct_ids,
                    sync_distinct_ids_to_ch,
                    mark_ch_only_orphans_deleted,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    SyncPersonDistinctIdsWorkflow.run,
                    SyncPersonDistinctIdsWorkflowInputs(
                        team_id=self.team.id,
                        person_ids=person_uuids,  # Specify exact persons to process
                        dry_run=False,
                        delete_ch_only_orphans=True,
                        categorize_orphans=True,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue_name,
                )

        # Verify workflow result
        assert result.dry_run is False
        assert result.total_orphaned_persons == 3
        assert result.persons_marked_deleted == 3

        # Verify each person is deleted with version+1
        for i, person_uuid in enumerate(person_uuids):
            ch_person = get_ch_person(self.team.id, person_uuid)
            assert ch_person is not None, f"Person {i} should exist"
            assert ch_person["is_deleted"] == 1, f"Person {i} should be deleted"
            assert (
                ch_person["version"] == versions[i] + 1
            ), f"Person {i} should have version {versions[i] + 1}, got {ch_person['version']}"
