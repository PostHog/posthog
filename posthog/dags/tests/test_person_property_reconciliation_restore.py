"""Integration tests for the person property restore job.

These tests use real database connections, not mocks.
"""

import json
import uuid as uuid_module
from datetime import UTC, datetime

import pytest

from django.db import connections

from posthog.dags.person_property_reconciliation_restore import (
    compute_restore_diff,
    fetch_backup_entries,
    fetch_backup_entries_paginated,
    fetch_person_by_id,
    fetch_persons_by_ids,
    restore_person_with_version_check,
)
from posthog.models import Organization, Person, Team
from posthog.person_db_router import PERSONS_DB_FOR_WRITE


def create_backup_entry(
    cursor,
    job_id: str,
    team_id: int,
    person_id: int,
    person_uuid: str,
    properties_before: dict,
    properties_after: dict,
    version_before: int = 1,
    version_after: int = 2,
    properties_last_updated_at_before: dict | None = None,
    properties_last_operation_before: dict | None = None,
    properties_last_updated_at_after: dict | None = None,
    properties_last_operation_after: dict | None = None,
) -> None:
    """Helper to insert a backup entry directly into the backup table."""
    cursor.execute(
        """
        INSERT INTO posthog_person_reconciliation_backup (
            job_id, team_id, person_id, uuid,
            properties, properties_last_updated_at, properties_last_operation,
            version, is_identified, created_at, is_user_id,
            pending_operations,
            properties_after, properties_last_updated_at_after,
            properties_last_operation_after, version_after
        ) VALUES (
            %s, %s, %s, %s::uuid,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s
        )
        """,
        (
            job_id,
            team_id,
            person_id,
            person_uuid,
            json.dumps(properties_before),
            json.dumps(properties_last_updated_at_before or {}),
            json.dumps(properties_last_operation_before or {}),
            version_before,
            False,
            datetime.now(UTC),
            None,
            json.dumps([]),  # pending_operations
            json.dumps(properties_after),
            json.dumps(properties_last_updated_at_after or {}),
            json.dumps(properties_last_operation_after or {}),
            version_after,
        ),
    )


class TestComputeRestoreDiff:
    """Unit tests for compute_restore_diff function."""

    def test_full_overwrite_returns_backup_state(self):
        """Test that full_overwrite completely replaces current with backup."""
        current_person = {
            "properties": {"email": "current@example.com", "new_prop": "added_after"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="full_overwrite")

        assert result == {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }

    def test_full_overwrite_returns_none_when_already_matches(self):
        """Test that full_overwrite returns None when current already matches backup."""
        current_person = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="full_overwrite")

        assert result is None

    def test_restore_wins_restores_backed_up_and_preserves_new(self):
        """Test that restore_wins restores backed-up properties and preserves new ones."""
        current_person = {
            "properties": {"email": "current@example.com", "new_prop": "added_after"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="restore_wins")

        assert result == {
            "properties": {"email": "original@example.com", "new_prop": "added_after"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }

    def test_keep_newer_only_restores_unchanged_properties(self):
        """Test that keep_newer only restores properties that haven't changed since backup."""
        current_person = {
            "properties": {
                "email": "reconciled@example.com",  # unchanged since backup
                "name": "Updated Name",  # changed after backup
            },
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_before = {
            "properties": {"email": "original@example.com", "name": "Original Name"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com", "name": "Reconciled Name"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="keep_newer")

        # email unchanged since backup (current == after), so restore to before
        # name was changed after backup (current != after), so keep current
        assert result == {
            "properties": {"email": "original@example.com", "name": "Updated Name"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

    def test_keep_newer_returns_none_when_all_changed(self):
        """Test keep_newer returns None when all properties changed after backup."""
        current_person = {
            "properties": {"email": "latest@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="keep_newer")

        # current != after, so property was changed after backup, keep it
        assert result is None

    def test_restore_wins_restores_metadata_when_present_in_backup(self):
        """Test that metadata is restored when it exists in the backup."""
        current_person = {
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-06-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set_once"},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="restore_wins")

        assert result == {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set_once"},
        }

    def test_restore_wins_removes_metadata_when_absent_from_backup(self):
        """Test that metadata is removed when it doesn't exist in the backup."""
        current_person = {
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-06-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            # No metadata for email in backup
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="restore_wins")

        assert result == {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

    def test_keep_newer_restores_metadata_correctly(self):
        """Test that keep_newer also restores metadata correctly."""
        current_person = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {"email": "2024-06-01T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set_once"},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="keep_newer")

        # Property restored since current == after, metadata also restored
        assert result == {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set_once"},
        }

    def test_metadata_preserved_for_unchanged_properties(self):
        """Test that metadata for properties not being restored stays unchanged."""
        current_person = {
            "properties": {"email": "current@example.com", "name": "Current Name"},
            "properties_last_updated_at": {"email": "2024-06-01T00:00:00", "name": "2024-06-01T00:00:00"},
            "properties_last_operation": {"email": "set", "name": "set"},
        }
        backup_before = {
            "properties": {"email": "original@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00"},
            "properties_last_operation": {"email": "set_once"},
        }
        backup_after = {
            "properties": {"email": "reconciled@example.com"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="restore_wins")

        # Email restored with metadata, name preserved as-is (not in backup)
        assert result == {
            "properties": {"email": "original@example.com", "name": "Current Name"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00", "name": "2024-06-01T00:00:00"},
            "properties_last_operation": {"email": "set_once", "name": "set"},
        }

    def test_full_overwrite_many_properties(self):
        """Test full_overwrite with many properties - complete replacement."""
        current_person = {
            "properties": {
                "email": "current@example.com",
                "name": "Current Name",
                "phone": "+1234567890",
                "new_prop_1": "added_after_backup",
                "new_prop_2": "also_added_after",
                "new_prop_3": "third_new_one",
            },
            "properties_last_updated_at": {
                "email": "2024-06-01T00:00:00",
                "name": "2024-06-01T00:00:00",
                "phone": "2024-06-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set",
                "name": "set",
                "phone": "set",
            },
        }
        backup_before = {
            "properties": {
                "email": "original@example.com",
                "name": "Original Name",
                "phone": "+0987654321",
            },
            "properties_last_updated_at": {
                "email": "2024-01-01T00:00:00",
                "name": "2024-01-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set_once",
                "name": "set",
            },
        }
        backup_after = {
            "properties": {
                "email": "reconciled@example.com",
                "name": "Reconciled Name",
                "phone": "+1111111111",
            },
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="full_overwrite")

        # Complete replacement - all current properties replaced with backup_before
        assert result == {
            "properties": {
                "email": "original@example.com",
                "name": "Original Name",
                "phone": "+0987654321",
            },
            "properties_last_updated_at": {
                "email": "2024-01-01T00:00:00",
                "name": "2024-01-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set_once",
                "name": "set",
            },
        }

    def test_restore_wins_many_properties(self):
        """Test restore_wins with many properties - restore backed-up, preserve new."""
        current_person = {
            "properties": {
                "email": "current@example.com",
                "name": "Current Name",
                "phone": "+1234567890",
                "new_prop_1": "added_after_backup",
                "new_prop_2": "also_added_after",
                "new_prop_3": "third_new_one",
            },
            "properties_last_updated_at": {
                "email": "2024-06-01T00:00:00",
                "name": "2024-06-01T00:00:00",
                "new_prop_1": "2024-06-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set",
                "name": "set",
                "new_prop_1": "set",
            },
        }
        backup_before = {
            "properties": {
                "email": "original@example.com",
                "name": "Original Name",
                "phone": "+0987654321",
            },
            "properties_last_updated_at": {
                "email": "2024-01-01T00:00:00",
                "name": "2024-01-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set_once",
                "name": "set",
            },
        }
        backup_after = {
            "properties": {
                "email": "reconciled@example.com",
                "name": "Reconciled Name",
                "phone": "+1111111111",
            },
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="restore_wins")

        # Backed-up properties restored, new properties preserved
        assert result == {
            "properties": {
                "email": "original@example.com",
                "name": "Original Name",
                "phone": "+0987654321",
                "new_prop_1": "added_after_backup",
                "new_prop_2": "also_added_after",
                "new_prop_3": "third_new_one",
            },
            "properties_last_updated_at": {
                "email": "2024-01-01T00:00:00",
                "name": "2024-01-01T00:00:00",
                "new_prop_1": "2024-06-01T00:00:00",
            },
            "properties_last_operation": {
                "email": "set_once",
                "name": "set",
                "new_prop_1": "set",
            },
        }

    def test_keep_newer_many_properties(self):
        """Test keep_newer with many properties - restore unchanged, keep changed."""
        current_person = {
            "properties": {
                # Unchanged since backup (current == after) - should restore
                "prop_unchanged_1": "reconciled_value_1",
                "prop_unchanged_2": "reconciled_value_2",
                "prop_unchanged_3": "reconciled_value_3",
                # Changed after backup (current != after) - should keep
                "prop_changed_1": "user_changed_1",
                "prop_changed_2": "user_changed_2",
                "prop_changed_3": "user_changed_3",
                # New properties not in backup - should keep
                "new_prop_1": "brand_new_1",
                "new_prop_2": "brand_new_2",
                "new_prop_3": "brand_new_3",
            },
            "properties_last_updated_at": {
                "prop_unchanged_1": "2024-06-01T00:00:00",
                "prop_changed_1": "2024-06-01T00:00:00",
            },
            "properties_last_operation": {
                "prop_unchanged_1": "set",
                "prop_changed_1": "set",
            },
        }
        backup_before = {
            "properties": {
                "prop_unchanged_1": "original_value_1",
                "prop_unchanged_2": "original_value_2",
                "prop_unchanged_3": "original_value_3",
                "prop_changed_1": "original_changed_1",
                "prop_changed_2": "original_changed_2",
                "prop_changed_3": "original_changed_3",
            },
            "properties_last_updated_at": {
                "prop_unchanged_1": "2024-01-01T00:00:00",
                "prop_changed_1": "2024-01-01T00:00:00",
            },
            "properties_last_operation": {
                "prop_unchanged_1": "set_once",
                "prop_changed_1": "set_once",
            },
        }
        backup_after = {
            "properties": {
                "prop_unchanged_1": "reconciled_value_1",
                "prop_unchanged_2": "reconciled_value_2",
                "prop_unchanged_3": "reconciled_value_3",
                "prop_changed_1": "reconciled_changed_1",
                "prop_changed_2": "reconciled_changed_2",
                "prop_changed_3": "reconciled_changed_3",
            },
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }

        result = compute_restore_diff(current_person, backup_before, backup_after, conflict_resolution="keep_newer")

        # Only unchanged properties restored; changed and new properties kept
        assert result == {
            "properties": {
                # Restored (current == after)
                "prop_unchanged_1": "original_value_1",
                "prop_unchanged_2": "original_value_2",
                "prop_unchanged_3": "original_value_3",
                # Kept (current != after)
                "prop_changed_1": "user_changed_1",
                "prop_changed_2": "user_changed_2",
                "prop_changed_3": "user_changed_3",
                # Kept (not in backup)
                "new_prop_1": "brand_new_1",
                "new_prop_2": "brand_new_2",
                "new_prop_3": "brand_new_3",
            },
            "properties_last_updated_at": {
                "prop_unchanged_1": "2024-01-01T00:00:00",
                "prop_changed_1": "2024-06-01T00:00:00",
            },
            "properties_last_operation": {
                "prop_unchanged_1": "set_once",
                "prop_changed_1": "set",
            },
        }


def get_persons_db_connection():
    """Get the correct database connection for person-related tables."""
    return connections[PERSONS_DB_FOR_WRITE]


@pytest.mark.django_db(transaction=True)
class TestRestoreIntegration:
    """Integration tests for restore functionality using real database."""

    @pytest.fixture(autouse=True)
    def setup_backup_table(self):
        """Create the backup table if it doesn't exist."""
        # Use persons database connection for backup table (since it references person_id)
        persons_conn = get_persons_db_connection()
        with persons_conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posthog_person_reconciliation_backup (
                    job_id TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    person_id BIGINT NOT NULL,
                    uuid UUID NOT NULL,
                    properties JSONB NOT NULL,
                    properties_last_updated_at JSONB,
                    properties_last_operation JSONB,
                    version BIGINT,
                    is_identified BOOLEAN NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    is_user_id INTEGER,
                    pending_operations JSONB NOT NULL,
                    properties_after JSONB,
                    properties_last_updated_at_after JSONB,
                    properties_last_operation_after JSONB,
                    version_after BIGINT,
                    backed_up_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (job_id, team_id, person_id)
                )
            """)

    @pytest.fixture
    def organization(self):
        """Create a test organization."""
        return Organization.objects.create(name="Test Organization")

    @pytest.fixture
    def team(self, organization):
        """Create a test team."""
        return Team.objects.create(organization=organization, name="Test Team")

    @pytest.fixture
    def person(self, team):
        """Create a test person."""
        return Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "current@example.com"},
            version=5,
        )

    def test_fetch_backup_entries(self, team, person):
        """Test fetching backup entries from database."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com"},
                properties_after={"email": "current@example.com"},
            )

            entries = fetch_backup_entries(cursor, job_id)

        assert len(entries) == 1
        assert entries[0]["team_id"] == team.id
        assert entries[0]["person_id"] == person.id
        # JSONB may be string or dict depending on cursor type
        props = entries[0]["properties"]
        if isinstance(props, str):
            props = json.loads(props)
        assert props == {"email": "original@example.com"}

    def test_fetch_backup_entries_with_person_filter(self, team, person):
        """Test fetching backup entries filtered by person_ids."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        person2 = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "other@example.com"},
            version=1,
        )

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original1@example.com"},
                properties_after={"email": "current1@example.com"},
            )
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person2.id,
                person_uuid=str(person2.uuid),
                properties_before={"email": "original2@example.com"},
                properties_after={"email": "current2@example.com"},
            )

            # Only fetch first person
            entries = fetch_backup_entries(cursor, job_id, team_ids=None, person_ids=[person.id])

        assert len(entries) == 1
        assert entries[0]["person_id"] == person.id

    def test_fetch_backup_entries_with_team_filter(self, organization, team, person):
        """Test fetching backup entries filtered by team_ids."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create a second team with a person
        team2 = Team.objects.create(organization=organization, name="Test Team 2")
        person2 = Person.objects.create(
            team_id=team2.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "other@example.com"},
            version=1,
        )

        with get_persons_db_connection().cursor() as cursor:
            # Create backup entries for both teams
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original1@example.com"},
                properties_after={"email": "current1@example.com"},
            )
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team2.id,
                person_id=person2.id,
                person_uuid=str(person2.uuid),
                properties_before={"email": "original2@example.com"},
                properties_after={"email": "current2@example.com"},
            )

            # Only fetch first team
            entries = fetch_backup_entries(cursor, job_id, team_ids=[team.id])

        assert len(entries) == 1
        assert entries[0]["team_id"] == team.id
        assert entries[0]["person_id"] == person.id

    def test_fetch_backup_entries_paginated(self, organization):
        """Test paginated fetch with small batch size."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 2 teams with 5 persons each = 10 entries
        team1 = Team.objects.create(organization=organization, name="Team 1")
        team2 = Team.objects.create(organization=organization, name="Team 2")

        persons = []
        for team in [team1, team2]:
            for i in range(5):
                p = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={"email": f"p{i}@example.com"},
                    version=1,
                )
                persons.append((team.id, p))

        with get_persons_db_connection().cursor() as cursor:
            # Create backup entries
            for team_id, person in persons:
                create_backup_entry(
                    cursor,
                    job_id=job_id,
                    team_id=team_id,
                    person_id=person.id,
                    person_uuid=str(person.uuid),
                    properties_before={"email": "original@example.com"},
                    properties_after={"email": f"p@example.com"},
                )

            # Fetch with batch_size=3, should get 4 batches (3+3+3+1)
            batches = list(fetch_backup_entries_paginated(cursor, job_id, batch_size=3))

        assert len(batches) == 4
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 3
        assert len(batches[3]) == 1

        # All entries should be returned in order
        all_entries = [e for batch in batches for e in batch]
        assert len(all_entries) == 10

        # Should be ordered by (team_id, person_id)
        for i in range(len(all_entries) - 1):
            current = (all_entries[i]["team_id"], all_entries[i]["person_id"])
            next_entry = (all_entries[i + 1]["team_id"], all_entries[i + 1]["person_id"])
            assert current < next_entry, "Entries should be ordered by (team_id, person_id)"

    def test_fetch_backup_entries_paginated_respects_filters(self, organization):
        """Test paginated fetch respects team_ids and person_ids filters."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        team1 = Team.objects.create(organization=organization, name="Team 1")
        team2 = Team.objects.create(organization=organization, name="Team 2")

        persons = {}
        for team in [team1, team2]:
            persons[team.id] = []
            for i in range(3):
                p = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={"email": f"p{i}@example.com"},
                    version=1,
                )
                persons[team.id].append(p)

        with get_persons_db_connection().cursor() as cursor:
            for team_id, team_persons in persons.items():
                for person in team_persons:
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team_id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={"email": "original@example.com"},
                        properties_after={"email": "current@example.com"},
                    )

            # Filter by team_ids
            batches = list(fetch_backup_entries_paginated(cursor, job_id, team_ids=[team1.id], batch_size=2))
            all_entries = [e for batch in batches for e in batch]
            assert len(all_entries) == 3
            assert all(e["team_id"] == team1.id for e in all_entries)

            # Filter by person_ids
            target_persons = [persons[team1.id][0].id, persons[team2.id][1].id]
            batches = list(fetch_backup_entries_paginated(cursor, job_id, person_ids=target_persons, batch_size=1))
            all_entries = [e for batch in batches for e in batch]
            assert len(all_entries) == 2
            assert all(e["person_id"] in target_persons for e in all_entries)

    def test_fetch_person_by_id(self, team, person):
        """Test fetching person by id."""
        with get_persons_db_connection().cursor() as cursor:
            fetched = fetch_person_by_id(cursor, team.id, person.id)

        assert fetched is not None
        assert fetched["id"] == person.id
        assert fetched["uuid"] == str(person.uuid)
        assert fetched["properties"] == {"email": "current@example.com"}

    def test_fetch_persons_by_ids(self, team):
        """Test batch fetching persons by ids."""
        # Create multiple persons
        persons = []
        for i in range(5):
            p = Person.objects.create(
                team_id=team.id,
                uuid=uuid_module.uuid4(),
                properties={"email": f"person{i}@example.com", "index": i},
                version=i + 1,
            )
            persons.append(p)

        person_ids = [p.id for p in persons]

        with get_persons_db_connection().cursor() as cursor:
            fetched = fetch_persons_by_ids(cursor, team.id, person_ids)

        assert len(fetched) == 5
        for p in persons:
            assert p.id in fetched
            assert fetched[p.id]["uuid"] == str(p.uuid)
            assert fetched[p.id]["properties"]["email"] == p.properties["email"]

    def test_fetch_persons_by_ids_partial(self, team):
        """Test batch fetching when some ids don't exist."""
        person = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "exists@example.com"},
            version=1,
        )

        # Include non-existent ids
        person_ids = [person.id, 99999, 99998]

        with get_persons_db_connection().cursor() as cursor:
            fetched = fetch_persons_by_ids(cursor, team.id, person_ids)

        # Only the existing person should be returned
        assert len(fetched) == 1
        assert person.id in fetched
        assert 99999 not in fetched
        assert 99998 not in fetched

    def test_restore_full_overwrite(self, team, person):
        """Test full_overwrite restore overwrites current state."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com", "name": "Original"},
                properties_after={"email": "current@example.com"},
                version_before=4,
                version_after=5,
            )

            backup_entry = fetch_backup_entries(cursor, job_id)[0]

            success, person_data = restore_person_with_version_check(
                cursor=cursor,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                backup_entry=backup_entry,
                conflict_resolution="full_overwrite",
                dry_run=False,
            )

        assert success is True
        assert person_data is not None

        person.refresh_from_db()
        assert person.properties == {"email": "original@example.com", "name": "Original"}
        assert person.version == 6

    def test_restore_keep_newer(self, team, person):
        """Test keep_newer restore preserves changed properties."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        # Set current state to match backup's "after" state for one property
        person.properties = {"email": "reconciled@example.com", "name": "User Changed This"}
        person.save()

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com", "name": "Original Name"},
                properties_after={"email": "reconciled@example.com", "name": "Reconciled Name"},
                version_before=4,
                version_after=5,
            )

            backup_entry = fetch_backup_entries(cursor, job_id)[0]

            success, person_data = restore_person_with_version_check(
                cursor=cursor,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                backup_entry=backup_entry,
                conflict_resolution="keep_newer",
                dry_run=False,
            )

        assert success is True
        assert person_data is not None

        person.refresh_from_db()
        # email: current == after, so restore to before
        assert person.properties["email"] == "original@example.com"
        # name: current != after (user changed it), so keep current
        assert person.properties["name"] == "User Changed This"

    def test_restore_restore_wins(self, team, person):
        """Test restore_wins restores all backed-up properties."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        person.properties = {"email": "current@example.com", "brand_new": "added_later"}
        person.save()

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com"},
                properties_after={"email": "reconciled@example.com"},
                version_before=4,
                version_after=5,
            )

            backup_entry = fetch_backup_entries(cursor, job_id)[0]

            success, person_data = restore_person_with_version_check(
                cursor=cursor,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                backup_entry=backup_entry,
                conflict_resolution="restore_wins",
                dry_run=False,
            )

        assert success is True
        assert person_data is not None

        person.refresh_from_db()
        # email should be restored to original
        assert person.properties["email"] == "original@example.com"
        # brand_new property added after backup should be preserved
        assert person.properties["brand_new"] == "added_later"

    def test_restore_dry_run_does_not_modify(self, team, person):
        """Test dry run mode doesn't modify the person."""
        job_id = f"test-job-{uuid_module.uuid4()}"
        original_properties = dict(person.properties)
        original_version = person.version

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com"},
                properties_after={"email": "current@example.com"},
            )

            backup_entry = fetch_backup_entries(cursor, job_id)[0]

            success, person_data = restore_person_with_version_check(
                cursor=cursor,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                backup_entry=backup_entry,
                conflict_resolution="full_overwrite",
                dry_run=True,
            )

        assert success is True
        assert person_data is None  # No data for Kafka in dry run

        person.refresh_from_db()
        assert person.properties == original_properties
        assert person.version == original_version

    def test_restore_skips_when_no_changes_needed(self, team, person):
        """Test restore returns success with no data when current matches backup."""
        job_id = f"test-job-{uuid_module.uuid4()}"

        # Set current to match backup's before state
        person.properties = {"email": "original@example.com"}
        person.save()

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com"},
                properties_after={"email": "reconciled@example.com"},
            )

            backup_entry = fetch_backup_entries(cursor, job_id)[0]

            success, person_data = restore_person_with_version_check(
                cursor=cursor,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                backup_entry=backup_entry,
                conflict_resolution="full_overwrite",
                dry_run=False,
            )

        assert success is True
        assert person_data is None  # No changes needed


@pytest.mark.django_db(transaction=True)
class TestRestoreJobEndToEnd:
    """End-to-end tests for the full Dagster job execution."""

    @pytest.fixture(autouse=True)
    def setup_backup_table(self):
        """Create the backup table if it doesn't exist."""
        persons_conn = get_persons_db_connection()
        with persons_conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posthog_person_reconciliation_backup (
                    job_id TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    person_id BIGINT NOT NULL,
                    uuid UUID NOT NULL,
                    properties JSONB NOT NULL,
                    properties_last_updated_at JSONB,
                    properties_last_operation JSONB,
                    version BIGINT,
                    is_identified BOOLEAN NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    is_user_id INTEGER,
                    pending_operations JSONB NOT NULL,
                    properties_after JSONB,
                    properties_last_updated_at_after JSONB,
                    properties_last_operation_after JSONB,
                    version_after BIGINT,
                    backed_up_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (job_id, team_id, person_id)
                )
            """)

    @pytest.fixture
    def organization(self):
        """Create a test organization."""
        return Organization.objects.create(name="Test Organization")

    @pytest.fixture
    def team(self, organization):
        """Create a test team."""
        return Team.objects.create(organization=organization, name="Test Team")

    @pytest.fixture
    def mock_kafka_producer(self):
        """Create a mock Kafka producer."""
        from unittest.mock import MagicMock

        producer = MagicMock()
        producer.flush = MagicMock()
        return producer

    def test_full_job_restores_persons(self, team, mock_kafka_producer, cluster):
        """Test that the full Dagster job restores persons correctly."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create test persons
        person1 = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "current1@example.com", "name": "Current Name"},
            version=5,
        )
        person2 = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "current2@example.com"},
            version=3,
        )

        # Create backup entries
        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person1.id,
                person_uuid=str(person1.uuid),
                properties_before={"email": "original1@example.com", "name": "Original Name"},
                properties_after={"email": "current1@example.com", "name": "Current Name"},
                version_before=4,
                version_after=5,
            )
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person2.id,
                person_uuid=str(person2.uuid),
                properties_before={"email": "original2@example.com", "extra": "prop"},
                properties_after={"email": "current2@example.com"},
                version_before=2,
                version_after=3,
            )

        # Create a Postgres resource that returns our connection
        persons_conn = get_persons_db_connection()

        # Run the job
        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify persons were restored
        person1.refresh_from_db()
        person2.refresh_from_db()

        assert person1.properties == {"email": "original1@example.com", "name": "Original Name"}
        assert person1.version == 6

        assert person2.properties == {"email": "original2@example.com", "extra": "prop"}
        assert person2.version == 4

        # Verify Kafka was called for each restored person
        assert mock_kafka_producer.produce.call_count == 2
        mock_kafka_producer.flush.assert_called()

    def test_full_job_with_team_filter(self, organization, team, mock_kafka_producer, cluster):
        """Test that team_ids filter works in the full job."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create a second team
        team2 = Team.objects.create(organization=organization, name="Test Team 2")

        # Create persons in both teams
        person1 = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "team1@example.com"},
            version=2,
        )
        person2 = Person.objects.create(
            team_id=team2.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "team2@example.com"},
            version=2,
        )

        # Create backup entries for both
        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person1.id,
                person_uuid=str(person1.uuid),
                properties_before={"email": "original1@example.com"},
                properties_after={"email": "team1@example.com"},
            )
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team2.id,
                person_id=person2.id,
                person_uuid=str(person2.uuid),
                properties_before={"email": "original2@example.com"},
                properties_after={"email": "team2@example.com"},
            )

        persons_conn = get_persons_db_connection()

        # Run the job with team_ids filter - only restore team 1
        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": [team.id],
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": [team.id],
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify only team 1 person was restored
        person1.refresh_from_db()
        person2.refresh_from_db()

        assert person1.properties == {"email": "original1@example.com"}
        assert person2.properties == {"email": "team2@example.com"}  # Unchanged

    def test_full_job_dry_run(self, team, mock_kafka_producer, cluster):
        """Test that dry_run mode doesn't modify data."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        person = Person.objects.create(
            team_id=team.id,
            uuid=uuid_module.uuid4(),
            properties={"email": "current@example.com"},
            version=5,
        )
        original_properties = dict(person.properties)
        original_version = person.version

        with get_persons_db_connection().cursor() as cursor:
            create_backup_entry(
                cursor,
                job_id=job_id,
                team_id=team.id,
                person_id=person.id,
                person_uuid=str(person.uuid),
                properties_before={"email": "original@example.com"},
                properties_after={"email": "current@example.com"},
            )

        persons_conn = get_persons_db_connection()

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": True,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": True,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify person was NOT modified
        person.refresh_from_db()
        assert person.properties == original_properties
        assert person.version == original_version

        # Verify Kafka was NOT called
        mock_kafka_producer.produce.assert_not_called()

    def test_full_job_many_teams_and_persons_restore_all(self, organization, mock_kafka_producer, cluster):
        """Test restoring all persons across many teams - verify data isolation."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 5 teams with 4 persons each = 20 persons total
        teams = []
        persons = {}  # {team_id: [person1, person2, ...]}

        for t in range(5):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(4):
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={
                        "email": f"current_t{t}_p{p}@example.com",
                        "team_marker": f"team_{t}",
                        "person_marker": f"person_{p}",
                    },
                    version=10 + p,
                )
                persons[team.id].append(person)

        # Create backup entries with distinct "before" data
        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={
                            "email": f"original_t{t}_p{p}@example.com",
                            "team_marker": f"team_{t}",
                            "person_marker": f"person_{p}",
                            "restored": True,
                        },
                        properties_after={
                            "email": f"current_t{t}_p{p}@example.com",
                            "team_marker": f"team_{t}",
                            "person_marker": f"person_{p}",
                        },
                        version_before=9 + p,
                        version_after=10 + p,
                    )

        persons_conn = get_persons_db_connection()

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify ALL 20 persons were restored with correct data
        for team in teams:
            t = teams.index(team)
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                assert person.properties == {
                    "email": f"original_t{t}_p{p}@example.com",
                    "team_marker": f"team_{t}",
                    "person_marker": f"person_{p}",
                    "restored": True,
                }, f"Person t{t}_p{p} has wrong properties: {person.properties}"
                assert person.version == 11 + p, f"Person t{t}_p{p} has wrong version: {person.version}"

        # Verify Kafka was called for all 20 persons
        assert mock_kafka_producer.produce.call_count == 20

    def test_full_job_many_teams_filter_some_teams(self, organization, mock_kafka_producer, cluster):
        """Test filtering to specific teams - only those teams should be restored."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 5 teams with 3 persons each
        teams = []
        persons = {}

        for t in range(5):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(3):
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={"email": f"current_t{t}_p{p}@example.com", "status": "current"},
                    version=5,
                )
                persons[team.id].append(person)

        # Create backup entries for all
        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={"email": f"original_t{t}_p{p}@example.com", "status": "restored"},
                        properties_after={"email": f"current_t{t}_p{p}@example.com", "status": "current"},
                    )

        persons_conn = get_persons_db_connection()

        # Only restore teams 1 and 3 (indices)
        teams_to_restore = [teams[1].id, teams[3].id]

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": teams_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": teams_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify teams 1 and 3 were restored
        for t_idx in [1, 3]:
            team = teams[t_idx]
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                assert person.properties["status"] == "restored", f"Team {t_idx} person {p} should be restored"
                assert person.properties["email"] == f"original_t{t_idx}_p{p}@example.com"

        # Verify teams 0, 2, 4 were NOT restored
        for t_idx in [0, 2, 4]:
            team = teams[t_idx]
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                assert person.properties["status"] == "current", f"Team {t_idx} person {p} should NOT be restored"
                assert person.properties["email"] == f"current_t{t_idx}_p{p}@example.com"

        # Verify Kafka was called for 6 persons (2 teams * 3 persons)
        assert mock_kafka_producer.produce.call_count == 6

    def test_full_job_filter_some_persons(self, organization, mock_kafka_producer, cluster):
        """Test filtering to specific person_ids - only those persons should be restored."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 3 teams with 5 persons each
        teams = []
        persons = {}
        all_persons = []

        for t in range(3):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(5):
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={"email": f"current_t{t}_p{p}@example.com", "restored": False},
                    version=5,
                )
                persons[team.id].append(person)
                all_persons.append(person)

        # Create backup entries for all
        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={"email": f"original_t{t}_p{p}@example.com", "restored": True},
                        properties_after={"email": f"current_t{t}_p{p}@example.com", "restored": False},
                    )

        persons_conn = get_persons_db_connection()

        # Only restore specific persons: first person from each team + last person from team 0
        persons_to_restore = [
            persons[teams[0].id][0].id,  # team 0, person 0
            persons[teams[0].id][4].id,  # team 0, person 4
            persons[teams[1].id][0].id,  # team 1, person 0
            persons[teams[2].id][0].id,  # team 2, person 0
        ]

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "person_ids": persons_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "person_ids": persons_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify only the selected persons were restored
        for person in all_persons:
            person.refresh_from_db()
            if person.id in persons_to_restore:
                assert person.properties["restored"] is True, f"Person {person.id} should be restored"
            else:
                assert person.properties["restored"] is False, f"Person {person.id} should NOT be restored"

        # Verify Kafka was called for 4 persons
        assert mock_kafka_producer.produce.call_count == 4

    def test_full_job_filter_teams_and_persons(self, organization, mock_kafka_producer, cluster):
        """Test filtering by both team_ids AND person_ids simultaneously."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 4 teams with 4 persons each = 16 persons
        teams = []
        persons = {}

        for t in range(4):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(4):
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={
                        "email": f"current_t{t}_p{p}@example.com",
                        "team_id": t,
                        "person_id": p,
                        "restored": False,
                    },
                    version=5,
                )
                persons[team.id].append(person)

        # Create backup entries for all
        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={
                            "email": f"original_t{t}_p{p}@example.com",
                            "team_id": t,
                            "person_id": p,
                            "restored": True,
                        },
                        properties_after={
                            "email": f"current_t{t}_p{p}@example.com",
                            "team_id": t,
                            "person_id": p,
                            "restored": False,
                        },
                    )

        persons_conn = get_persons_db_connection()

        # Filter to teams 0 and 2, AND persons 1 and 3 within those teams
        # This should restore: team0/person1, team0/person3, team2/person1, team2/person3
        teams_to_restore = [teams[0].id, teams[2].id]
        persons_to_restore = [
            persons[teams[0].id][1].id,
            persons[teams[0].id][3].id,
            persons[teams[2].id][1].id,
            persons[teams[2].id][3].id,
        ]

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": teams_to_restore,
                            "person_ids": persons_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "team_ids": teams_to_restore,
                            "person_ids": persons_to_restore,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify exactly the right persons were restored
        expected_restored = {
            (0, 1): True,
            (0, 3): True,
            (2, 1): True,
            (2, 3): True,
        }

        for team in teams:
            t = teams.index(team)
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                should_restore = expected_restored.get((t, p), False)

                if should_restore:
                    assert person.properties["restored"] is True, f"t{t}_p{p} should be restored"
                    assert person.properties["email"] == f"original_t{t}_p{p}@example.com"
                else:
                    assert person.properties["restored"] is False, f"t{t}_p{p} should NOT be restored"
                    assert person.properties["email"] == f"current_t{t}_p{p}@example.com"

        # Verify Kafka was called for 4 persons
        assert mock_kafka_producer.produce.call_count == 4

    def test_full_job_restore_wins_preserves_new_properties(self, organization, mock_kafka_producer, cluster):
        """Test restore_wins mode with many persons - new properties should be preserved."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 3 teams with 3 persons each
        teams = []
        persons = {}

        for t in range(3):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(3):
                # Current state has properties added after backup
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={
                        "email": f"current_t{t}_p{p}@example.com",
                        "name": f"Current Name {t}_{p}",
                        "new_after_backup": f"new_value_t{t}_p{p}",  # Added after backup
                    },
                    version=5,
                )
                persons[team.id].append(person)

        # Create backup entries - "before" doesn't have new_after_backup
        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={
                            "email": f"original_t{t}_p{p}@example.com",
                            "name": f"Original Name {t}_{p}",
                        },
                        properties_after={
                            "email": f"current_t{t}_p{p}@example.com",
                            "name": f"Current Name {t}_{p}",
                        },
                    )

        persons_conn = get_persons_db_connection()

        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "restore_wins",
                            "dry_run": False,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "restore_wins",
                            "dry_run": False,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify all persons have:
        # - email and name restored to original
        # - new_after_backup preserved
        for team in teams:
            t = teams.index(team)
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                assert person.properties == {
                    "email": f"original_t{t}_p{p}@example.com",
                    "name": f"Original Name {t}_{p}",
                    "new_after_backup": f"new_value_t{t}_p{p}",  # Preserved!
                }, f"Person t{t}_p{p} has wrong properties: {person.properties}"

        # All 9 persons restored
        assert mock_kafka_producer.produce.call_count == 9

    def test_full_job_with_small_batch_size(self, organization, mock_kafka_producer, cluster):
        """Test that batching works correctly with small batch sizes."""
        from posthog.dags.person_property_reconciliation_restore import (
            person_property_reconciliation_restore_from_backup,
        )

        job_id = f"test-job-{uuid_module.uuid4()}"

        # Create 3 teams with 2, 2, 1 persons = 5 total
        # With batch_size=2, this gives 3 batches (2, 2, 1) - last batch not full
        teams = []
        persons = {}
        persons_per_team = [2, 2, 1]

        for t in range(3):
            team = Team.objects.create(organization=organization, name=f"Team {t}")
            teams.append(team)
            persons[team.id] = []

            for p in range(persons_per_team[t]):
                person = Person.objects.create(
                    team_id=team.id,
                    uuid=uuid_module.uuid4(),
                    properties={"email": f"current_t{t}_p{p}@example.com"},
                    version=5,
                )
                persons[team.id].append(person)

        with get_persons_db_connection().cursor() as cursor:
            for team in teams:
                t = teams.index(team)
                for p, person in enumerate(persons[team.id]):
                    create_backup_entry(
                        cursor,
                        job_id=job_id,
                        team_id=team.id,
                        person_id=person.id,
                        person_uuid=str(person.uuid),
                        properties_before={"email": f"original_t{t}_p{p}@example.com", "restored": True},
                        properties_after={"email": f"current_t{t}_p{p}@example.com"},
                    )

        persons_conn = get_persons_db_connection()

        # Run with batch_size=2 to test pagination (3 batches: 2, 2, 1)
        result = person_property_reconciliation_restore_from_backup.execute_in_process(
            run_config={
                "ops": {
                    "get_backup_entries_by_team": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                            "backup_batch_size": 2,
                        }
                    },
                    "restore_team_chunk": {
                        "config": {
                            "job_id": job_id,
                            "conflict_resolution": "full_overwrite",
                            "dry_run": False,
                            "backup_batch_size": 2,
                        }
                    },
                }
            },
            resources={
                "cluster": cluster,
                "persons_database": persons_conn,
                "kafka_producer": mock_kafka_producer,
            },
        )

        assert result.success

        # Verify all 5 persons were restored correctly
        for team in teams:
            t = teams.index(team)
            for p, person in enumerate(persons[team.id]):
                person.refresh_from_db()
                assert person.properties == {
                    "email": f"original_t{t}_p{p}@example.com",
                    "restored": True,
                }, f"Person t{t}_p{p} has wrong properties"

        # All 5 persons restored
        assert mock_kafka_producer.produce.call_count == 5
