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
        assert len(result.mappings[0].distinct_id_versions) == 1
        assert distinct_id in result.mappings[0].distinct_id_versions
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
        """Each distinct ID should be returned with its own version."""
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
        assert len(result.mappings[0].distinct_id_versions) == 3
        assert set(result.mappings[0].distinct_id_versions.keys()) == set(distinct_ids)
        # Each distinct ID should have its own version, not the max
        assert result.mappings[0].distinct_id_versions[distinct_ids[0]] == 0
        assert result.mappings[0].distinct_id_versions[distinct_ids[1]] == 1
        assert result.mappings[0].distinct_id_versions[distinct_ids[2]] == 2
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

        mapping = PersonDistinctIdMapping(person_uuid=person_uuid, distinct_id_versions={distinct_id: 0})

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

        mapping = PersonDistinctIdMapping(person_uuid=person_uuid, distinct_id_versions={distinct_id: 0})

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

        mapping = PersonDistinctIdMapping(
            person_uuid=person_uuid, distinct_id_versions={did: 0 for did in distinct_ids}
        )

        result: SyncDistinctIdsToChResult = await self.activity_environment.run(
            sync_distinct_ids_to_ch,
            SyncDistinctIdsToChInputs(team_id=self.team.id, mappings=[mapping], dry_run=False),
        )

        assert result.distinct_ids_synced == 3
        assert result.persons_synced == 1

    @pytest.mark.asyncio
    async def test_syncs_distinct_ids_with_individual_versions(self):
        """Each distinct ID should be synced with its own version from PostgreSQL.

        This is important because distinct ID versions are per-DID, not per-person.
        They increment during merges when DIDs move between persons. If we use
        the wrong version, future merges might be ignored because the new version
        after merging could be lower in PG than what we synced to CH.
        """
        person_uuid = str(uuid.uuid4())
        did1 = f"{self.prefix}-version-0"
        did2 = f"{self.prefix}-version-5"
        self.created_person_uuids.append(person_uuid)
        self.created_distinct_ids.extend([did1, did2])
        insert_person_to_ch(self.team.id, person_uuid, version=0)

        # Simulate distinct IDs with different versions (e.g., did2 went through more merges)
        mapping = PersonDistinctIdMapping(
            person_uuid=person_uuid,
            distinct_id_versions={did1: 0, did2: 5},
        )

        result: SyncDistinctIdsToChResult = await self.activity_environment.run(
            sync_distinct_ids_to_ch,
            SyncDistinctIdsToChInputs(team_id=self.team.id, mappings=[mapping], dry_run=False),
        )

        assert result.distinct_ids_synced == 2
        assert result.persons_synced == 1

        # Verify each distinct ID has its correct version in ClickHouse
        ch_did1 = get_ch_distinct_id(self.team.id, did1)
        ch_did2 = get_ch_distinct_id(self.team.id, did2)

        assert ch_did1 is not None
        assert ch_did1["version"] == 0  # did1 should have version 0
        assert str(ch_did1["person_id"]) == person_uuid

        assert ch_did2 is not None
        assert ch_did2["version"] == 5  # did2 should have version 5
        assert str(ch_did2["person_id"]) == person_uuid


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
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_versions={person_uuid: 0}, dry_run=True),
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
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_versions={person_uuid: 0}, dry_run=False),
        )

        assert result.persons_marked_deleted == 1

    @pytest.mark.asyncio
    async def test_marks_multiple_persons_as_deleted(self):
        person_uuids = [str(uuid.uuid4()) for _ in range(3)]
        for person_uuid in person_uuids:
            self.created_person_uuids.append(person_uuid)
            insert_person_to_ch(self.team.id, person_uuid, version=0)

        person_versions = {uuid: 0 for uuid in person_uuids}
        result: MarkChOnlyOrphansDeletedResult = await self.activity_environment.run(
            mark_ch_only_orphans_deleted,
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_versions=person_versions, dry_run=False),
        )

        assert result.persons_marked_deleted == 3

    @pytest.mark.asyncio
    async def test_marks_person_with_high_version_as_deleted(self):
        """Person with high version should still be marked as deleted.

        The version used for deletion must be higher than the person's current
        version, otherwise ClickHouse's ReplacingMergeTree will keep the old
        (non-deleted) record.
        """
        person_uuid = str(uuid.uuid4())
        self.created_person_uuids.append(person_uuid)
        # Create person with high version (1000)
        insert_person_to_ch(self.team.id, person_uuid, version=1000)

        # Verify person exists and is not deleted
        ch_person_before = get_ch_person(self.team.id, person_uuid)
        assert ch_person_before is not None
        assert ch_person_before["is_deleted"] == 0
        assert ch_person_before["version"] == 1000

        result: MarkChOnlyOrphansDeletedResult = await self.activity_environment.run(
            mark_ch_only_orphans_deleted,
            MarkChOnlyOrphansDeletedInputs(team_id=self.team.id, person_versions={person_uuid: 1000}, dry_run=False),
        )

        assert result.persons_marked_deleted == 1

        # Verify person is now marked as deleted (using FINAL to get merged result)
        ch_person_after = get_ch_person(self.team.id, person_uuid)
        assert ch_person_after is not None
        assert ch_person_after["is_deleted"] == 1, (
            f"Person should be deleted but is_deleted={ch_person_after['is_deleted']}, "
            f"version={ch_person_after['version']} (original was 1000)"
        )


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
