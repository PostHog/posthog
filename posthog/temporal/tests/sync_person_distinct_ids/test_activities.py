"""Integration tests for sync_person_distinct_ids activities."""

import uuid

import pytest

from asgiref.sync import sync_to_async

from posthog.models.person import Person, PersonDistinctId
from posthog.person_db_router import PERSONS_DB_FOR_WRITE
from posthog.temporal.sync_person_distinct_ids.activities import (
    FindOrphanedPersonsInputs,
    FindOrphanedPersonsResult,
    LookupPgDistinctIdsInputs,
    LookupPgDistinctIdsResult,
    MarkChOnlyOrphansDeletedInputs,
    MarkChOnlyOrphansDeletedResult,
    PersonDistinctIdMapping,
    SyncDistinctIdsToChInputs,
    SyncDistinctIdsToChResult,
    find_orphaned_persons,
    lookup_pg_distinct_ids,
    mark_ch_only_orphans_deleted,
    sync_distinct_ids_to_ch,
)
from posthog.temporal.tests.sync_person_distinct_ids.conftest import (
    cleanup_ch_test_data,
    get_ch_distinct_id,
    get_ch_person,
    get_orphaned_person_count,
    insert_distinct_id_to_ch,
    insert_person_to_ch,
)


@pytest.mark.django_db(transaction=True)
class TestFindOrphanedPersons:
    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_person_uuids: list[str] = []
        self.created_distinct_ids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, self.created_distinct_ids)
        PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, distinct_id__startswith=self.prefix
        ).delete()
        Person.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, uuid__in=self.created_person_uuids
        ).delete()

    @pytest.mark.asyncio
    async def test_finds_orphaned_persons_without_distinct_ids(self):
        assert get_orphaned_person_count(self.team.id) == 0

        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        result: FindOrphanedPersonsResult = await self.activity_environment.run(
            find_orphaned_persons,
            FindOrphanedPersonsInputs(team_id=self.team.id),
        )

        assert len(result.orphaned_persons) == 1
        assert result.orphaned_persons[0].person_id == person_uuid

    @pytest.mark.asyncio
    async def test_does_not_find_persons_with_distinct_ids(self):
        assert get_orphaned_person_count(self.team.id) == 0

        person_uuid = str(uuid.uuid4())
        distinct_id = f"{self.prefix}-has-did"
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.append(distinct_id)
        insert_person_to_ch(self.team.id, person_uuid, version=0)
        insert_distinct_id_to_ch(self.team.id, person_uuid, distinct_id, version=0)

        result: FindOrphanedPersonsResult = await self.activity_environment.run(
            find_orphaned_persons,
            FindOrphanedPersonsInputs(team_id=self.team.id),
        )

        assert len(result.orphaned_persons) == 0

    @pytest.mark.asyncio
    async def test_does_not_find_deleted_persons(self):
        assert get_orphaned_person_count(self.team.id) == 0

        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)
        insert_person_to_ch(self.team.id, person_uuid, version=0, is_deleted=1)

        result: FindOrphanedPersonsResult = await self.activity_environment.run(
            find_orphaned_persons,
            FindOrphanedPersonsInputs(team_id=self.team.id),
        )

        assert len(result.orphaned_persons) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        assert get_orphaned_person_count(self.team.id) == 0

        person_uuids = [str(uuid.uuid4()) for _ in range(5)]
        for person_uuid in person_uuids:
            self.created_person_uuids.append(person_uuid)
            insert_person_to_ch(self.team.id, person_uuid, version=0)

        assert get_orphaned_person_count(self.team.id) == 5

        result: FindOrphanedPersonsResult = await self.activity_environment.run(
            find_orphaned_persons,
            FindOrphanedPersonsInputs(team_id=self.team.id, limit=2),
        )

        assert len(result.orphaned_persons) == 2


@pytest.mark.django_db(transaction=True)
class TestLookupPgDistinctIds:
    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_person_uuids: list[str] = []
        self.created_distinct_ids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, self.created_distinct_ids)
        PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, distinct_id__startswith=self.prefix
        ).delete()
        Person.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, uuid__in=self.created_person_uuids
        ).delete()

    @pytest.mark.asyncio
    async def test_finds_distinct_ids_for_fixable_orphans(self):
        person_uuid = str(uuid.uuid4())
        distinct_id = f"{self.prefix}-fixable"
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.append(distinct_id)

        @sync_to_async
        def create_person_with_did():
            person = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(team=self.team, uuid=person_uuid)
            PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                team=self.team, person=person, distinct_id=distinct_id, version=0
            )

        await create_person_with_did()

        result: LookupPgDistinctIdsResult = await self.activity_environment.run(
            lookup_pg_distinct_ids,
            LookupPgDistinctIdsInputs(team_id=self.team.id, person_uuids=[person_uuid]),
        )

        assert len(result.mappings) == 1
        assert result.mappings[0].person_uuid == person_uuid
        assert len(result.mappings[0].distinct_ids) == 1
        assert distinct_id in result.mappings[0].distinct_ids
        assert len(result.persons_not_found) == 0

    @pytest.mark.asyncio
    async def test_returns_persons_not_found_for_ch_only_orphans(self):
        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)

        result: LookupPgDistinctIdsResult = await self.activity_environment.run(
            lookup_pg_distinct_ids,
            LookupPgDistinctIdsInputs(team_id=self.team.id, person_uuids=[person_uuid]),
        )

        assert len(result.mappings) == 0
        assert len(result.persons_not_found) == 1
        assert person_uuid in result.persons_not_found

    @pytest.mark.asyncio
    async def test_categorizes_truly_orphaned_vs_ch_only(self):
        truly_orphaned_uuid = str(uuid.uuid4())
        ch_only_uuid = str(uuid.uuid4())
        self.created_person_uuids.extend([truly_orphaned_uuid, ch_only_uuid])

        @sync_to_async
        def create_person():
            Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(team=self.team, uuid=truly_orphaned_uuid)

        await create_person()

        result: LookupPgDistinctIdsResult = await self.activity_environment.run(
            lookup_pg_distinct_ids,
            LookupPgDistinctIdsInputs(
                team_id=self.team.id,
                person_uuids=[truly_orphaned_uuid, ch_only_uuid],
                categorize_not_found=True,
            ),
        )

        assert len(result.mappings) == 0
        assert len(result.persons_not_found) == 2
        assert truly_orphaned_uuid in result.persons_not_found
        assert ch_only_uuid in result.persons_not_found
        assert len(result.persons_truly_orphaned) == 1
        assert truly_orphaned_uuid in result.persons_truly_orphaned
        assert len(result.persons_ch_only) == 1
        assert ch_only_uuid in result.persons_ch_only

    @pytest.mark.asyncio
    async def test_finds_multiple_distinct_ids_for_person(self):
        person_uuid = str(uuid.uuid4())
        distinct_ids = [f"{self.prefix}-multi-{i}" for i in range(3)]
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.extend(distinct_ids)

        @sync_to_async
        def create_person_with_dids():
            person = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(team=self.team, uuid=person_uuid)
            for i, distinct_id in enumerate(distinct_ids):
                PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                    team=self.team, person=person, distinct_id=distinct_id, version=i
                )

        await create_person_with_dids()

        result: LookupPgDistinctIdsResult = await self.activity_environment.run(
            lookup_pg_distinct_ids,
            LookupPgDistinctIdsInputs(team_id=self.team.id, person_uuids=[person_uuid]),
        )

        assert len(result.mappings) == 1
        assert len(result.mappings[0].distinct_ids) == 3
        assert set(result.mappings[0].distinct_ids) == set(distinct_ids)
        assert result.mappings[0].version == 2  # Max version
        assert len(result.persons_not_found) == 0


@pytest.mark.django_db(transaction=True)
class TestSyncDistinctIdsToCh:
    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_person_uuids: list[str] = []
        self.created_distinct_ids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, self.created_distinct_ids)

    @pytest.mark.asyncio
    async def test_dry_run_does_not_sync(self):
        person_uuid = str(uuid.uuid4())
        distinct_id = f"{self.prefix}-dry-run"
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.append(distinct_id)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        mapping = PersonDistinctIdMapping(person_uuid=person_uuid, distinct_ids=[distinct_id], version=0)

        result: SyncDistinctIdsToChResult = await self.activity_environment.run(
            sync_distinct_ids_to_ch,
            SyncDistinctIdsToChInputs(team_id=self.team.id, mappings=[mapping], dry_run=True),
        )

        assert result.distinct_ids_synced == 1
        assert result.persons_synced == 1
        assert get_ch_distinct_id(self.team.id, distinct_id) is None

    @pytest.mark.asyncio
    async def test_syncs_distinct_ids_to_ch(self):
        person_uuid = str(uuid.uuid4())
        distinct_id = f"{self.prefix}-sync"
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.append(distinct_id)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        mapping = PersonDistinctIdMapping(person_uuid=person_uuid, distinct_ids=[distinct_id], version=0)

        result: SyncDistinctIdsToChResult = await self.activity_environment.run(
            sync_distinct_ids_to_ch,
            SyncDistinctIdsToChInputs(team_id=self.team.id, mappings=[mapping], dry_run=False),
        )

        assert result.distinct_ids_synced == 1
        assert result.persons_synced == 1

    @pytest.mark.asyncio
    async def test_syncs_multiple_distinct_ids(self):
        person_uuid = str(uuid.uuid4())
        distinct_ids = [f"{self.prefix}-multi-{i}" for i in range(3)]
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.extend(distinct_ids)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        mapping = PersonDistinctIdMapping(person_uuid=person_uuid, distinct_ids=distinct_ids, version=0)

        result: SyncDistinctIdsToChResult = await self.activity_environment.run(
            sync_distinct_ids_to_ch,
            SyncDistinctIdsToChInputs(team_id=self.team.id, mappings=[mapping], dry_run=False),
        )

        assert result.distinct_ids_synced == 3
        assert result.persons_synced == 1


@pytest.mark.django_db(transaction=True)
class TestMarkChOnlyOrphansDeleted:
    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_person_uuids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, [])

    @pytest.mark.asyncio
    async def test_dry_run_does_not_delete(self):
        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        result: MarkChOnlyOrphansDeletedResult = await self.activity_environment.run(
            mark_ch_only_orphans_deleted,
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_uuids=[person_uuid], dry_run=True),
        )

        assert result.persons_marked_deleted == 1
        ch_person = get_ch_person(self.team.id, person_uuid)
        assert ch_person is not None
        assert ch_person["is_deleted"] == 0

    @pytest.mark.asyncio
    async def test_marks_persons_as_deleted(self):
        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        result: MarkChOnlyOrphansDeletedResult = await self.activity_environment.run(
            mark_ch_only_orphans_deleted,
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_uuids=[person_uuid], dry_run=False),
        )

        assert result.persons_marked_deleted == 1

    @pytest.mark.asyncio
    async def test_marks_multiple_persons_as_deleted(self):
        person_uuids = [str(uuid.uuid4()) for _ in range(3)]
        for person_uuid in person_uuids:
            self.created_person_uuids.append(person_uuid)
            insert_person_to_ch(self.team.id, person_uuid, version=0)

        result: MarkChOnlyOrphansDeletedResult = await self.activity_environment.run(
            mark_ch_only_orphans_deleted,
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_uuids=person_uuids, dry_run=False),
        )

        assert result.persons_marked_deleted == 3


@pytest.mark.django_db(transaction=True)
class TestEndToEndOrphanCategories:
    """Test the complete flow of finding and categorizing all orphan types."""

    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_person_uuids: list[str] = []
        self.created_distinct_ids: list[str] = []

        yield

        cleanup_ch_test_data(self.team.id, self.created_person_uuids, self.created_distinct_ids)
        PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, distinct_id__startswith=self.prefix
        ).delete()
        Person.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=self.team, uuid__in=self.created_person_uuids
        ).delete()

    @pytest.mark.asyncio
    async def test_categorizes_all_three_orphan_types(self):
        """Test that lookup_pg_distinct_ids correctly categorizes all three orphan types."""
        fixable_uuid = str(uuid.uuid4())
        fixable_did = f"{self.prefix}-fixable"
        truly_orphaned_uuid = str(uuid.uuid4())
        ch_only_uuid = str(uuid.uuid4())

        self.created_person_uuids.extend([fixable_uuid, truly_orphaned_uuid, ch_only_uuid])
        self.created_distinct_ids.append(fixable_did)

        # Create PG data with sync_to_async
        @sync_to_async
        def create_pg_data():
            # Fixable: Person in PG with DID
            person = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(team=self.team, uuid=fixable_uuid)
            PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                team=self.team, person=person, distinct_id=fixable_did, version=0
            )
            # Truly orphaned: Person in PG, no DID
            Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(team=self.team, uuid=truly_orphaned_uuid)
            # CH-only: No PG data

        await create_pg_data()

        # Lookup all three UUIDs in PG with categorization
        # (simulating what would happen after find_orphaned_persons)
        lookup_result: LookupPgDistinctIdsResult = await self.activity_environment.run(
            lookup_pg_distinct_ids,
            LookupPgDistinctIdsInputs(
                team_id=self.team.id,
                person_uuids=[fixable_uuid, truly_orphaned_uuid, ch_only_uuid],
                categorize_not_found=True,
            ),
        )

        # Verify fixable
        assert len(lookup_result.mappings) == 1
        mapping_uuids = [m.person_uuid for m in lookup_result.mappings]
        assert fixable_uuid in mapping_uuids
        assert truly_orphaned_uuid not in mapping_uuids
        assert ch_only_uuid not in mapping_uuids

        # Verify truly orphaned
        assert len(lookup_result.persons_truly_orphaned) == 1
        assert truly_orphaned_uuid in lookup_result.persons_truly_orphaned
        assert fixable_uuid not in lookup_result.persons_truly_orphaned
        assert ch_only_uuid not in lookup_result.persons_truly_orphaned

        # Verify CH-only
        assert len(lookup_result.persons_ch_only) == 1
        assert ch_only_uuid in lookup_result.persons_ch_only
        assert fixable_uuid not in lookup_result.persons_ch_only
        assert truly_orphaned_uuid not in lookup_result.persons_ch_only
