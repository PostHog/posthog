from datetime import datetime
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.dags.fix_missing_person_overrides import (
    fix_missing_person_overrides_job,
    get_existing_override,
    get_mismatched_distinct_ids,
    get_missing_overrides_for_distinct_ids,
    insert_override_batch,
)


def insert_pdi2_records(records: list[tuple[int, str, UUID, int, int]]) -> None:
    """Insert records into person_distinct_id2: (team_id, distinct_id, person_id, version, is_deleted)"""
    sync_execute(
        "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, version, is_deleted) VALUES",
        records,
    )


def insert_override_records(records: list[tuple[int, str, UUID, int, int]]) -> None:
    """Insert records into person_distinct_id_overrides: (team_id, distinct_id, person_id, version, is_deleted)"""
    sync_execute(
        "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted, _timestamp, _offset, _partition) VALUES",
        [(r[0], r[1], r[2], r[3], r[4], datetime(2025, 1, 1), 0, 0) for r in records],
    )


def get_all_overrides(team_id: int) -> list[tuple[str, str]]:
    """Get all overrides for a team: (distinct_id, person_id)"""
    result = sync_execute(
        """
        SELECT distinct_id, argMax(person_id, version) as person_id
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
        """,
        {"team_id": team_id},
    )
    return [(row[0], str(row[1])) for row in result]


class TestGetMismatchedDistinctIds(ClickhouseTestMixin, BaseTest):
    def test_finds_distinct_ids_where_override_differs_from_pdi2(self):
        """When an override exists, person_id on events differs from pdi.person_id."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 says distinct_id "user_a" -> old_person_id
        insert_pdi2_records([(self.team.id, "user_a", old_person_id, 1, 0)])

        # Override says distinct_id "user_a" -> new_person_id
        insert_override_records([(self.team.id, "user_a", new_person_id, 1, 0)])

        # Create an event with this distinct_id
        _create_event(
            event="test_event",
            distinct_id="user_a",
            team=self.team,
        )
        flush_persons_and_events()

        # The HogQL query should find the distinct_id with a mismatch
        result = get_mismatched_distinct_ids(self.team)

        assert len(result) == 1
        assert result[0] == "user_a"

    def test_returns_empty_when_no_mismatches(self):
        """When override matches pdi2, no mismatch is detected."""
        person_id = uuid4()

        # pdi2 says distinct_id "user_b" -> person_id
        insert_pdi2_records([(self.team.id, "user_b", person_id, 1, 0)])

        # Override also says distinct_id "user_b" -> same person_id
        insert_override_records([(self.team.id, "user_b", person_id, 1, 0)])

        # Create an event
        _create_event(
            event="test_event",
            distinct_id="user_b",
            team=self.team,
        )
        flush_persons_and_events()

        result = get_mismatched_distinct_ids(self.team)

        assert len(result) == 0

    def test_returns_empty_when_no_events_exist(self):
        """When no events exist, no mismatches are found."""
        result = get_mismatched_distinct_ids(self.team)
        assert len(result) == 0

    def test_min_date_filters_events(self):
        """Events before min_date are excluded."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        insert_pdi2_records([(self.team.id, "user_date", old_person_id, 1, 0)])
        insert_override_records([(self.team.id, "user_date", new_person_id, 1, 0)])

        # Create event in January 2024
        _create_event(
            event="old_event",
            distinct_id="user_date",
            team=self.team,
            timestamp=datetime(2024, 1, 15),
        )
        flush_persons_and_events()

        # Query with min_date in February - should find nothing
        result = get_mismatched_distinct_ids(self.team, min_date="2024-02-01")
        assert len(result) == 0

        # Query with min_date in January - should find the mismatch
        result = get_mismatched_distinct_ids(self.team, min_date="2024-01-01")
        assert len(result) == 1

    def test_max_date_filters_events(self):
        """Events on or after max_date are excluded."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        insert_pdi2_records([(self.team.id, "user_max", old_person_id, 1, 0)])
        insert_override_records([(self.team.id, "user_max", new_person_id, 1, 0)])

        # Create event in March 2024
        _create_event(
            event="march_event",
            distinct_id="user_max",
            team=self.team,
            timestamp=datetime(2024, 3, 15),
        )
        flush_persons_and_events()

        # Query with max_date in March - should find nothing (exclusive)
        result = get_mismatched_distinct_ids(self.team, max_date="2024-03-01")
        assert len(result) == 0

        # Query with max_date in April - should find the mismatch
        result = get_mismatched_distinct_ids(self.team, max_date="2024-04-01")
        assert len(result) == 1

    def test_date_range_filters_events(self):
        """Only events within the date range are included."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        insert_pdi2_records([(self.team.id, "user_range", old_person_id, 1, 0)])
        insert_override_records([(self.team.id, "user_range", new_person_id, 1, 0)])

        # Create event in February 2024
        _create_event(
            event="feb_event",
            distinct_id="user_range",
            team=self.team,
            timestamp=datetime(2024, 2, 15),
        )
        flush_persons_and_events()

        # Query with range that excludes the event
        result = get_mismatched_distinct_ids(self.team, min_date="2024-03-01", max_date="2024-04-01")
        assert len(result) == 0

        # Query with range that includes the event
        result = get_mismatched_distinct_ids(self.team, min_date="2024-02-01", max_date="2024-03-01")
        assert len(result) == 1


class TestInsertOverrideBatch(ClickhouseTestMixin, BaseTest):
    def test_inserts_batch_of_overrides(self):
        person_id_1 = uuid4()
        person_id_2 = uuid4()

        insert_override_batch(
            [
                (self.team.id, "batch_user_1", str(person_id_1), 1),
                (self.team.id, "batch_user_2", str(person_id_1), 1),
                (self.team.id, "batch_user_3", str(person_id_2), 2),
            ]
        )

        result = get_existing_override(self.team.id, "batch_user_1")
        assert result is not None
        assert result[0] == str(person_id_1)

        result = get_existing_override(self.team.id, "batch_user_2")
        assert result is not None
        assert result[0] == str(person_id_1)

        result = get_existing_override(self.team.id, "batch_user_3")
        assert result is not None
        assert result[0] == str(person_id_2)

    def test_handles_empty_batch(self):
        insert_override_batch([])


class TestGetMissingOverridesForDistinctIds(ClickhouseTestMixin, BaseTest):
    def test_returns_empty_for_empty_distinct_ids(self):
        result = get_missing_overrides_for_distinct_ids(self.team.id, [])
        assert len(result) == 0

    def test_returns_empty_for_nonexistent_distinct_id(self):
        result = get_missing_overrides_for_distinct_ids(self.team.id, ["nonexistent_user"])
        assert len(result) == 0

    def test_returns_missing_overrides(self):
        person_id = uuid4()

        # Insert test data - two distinct_ids mapping to the same person
        insert_pdi2_records(
            [
                (self.team.id, "has_override", person_id, 1, 0),
                (self.team.id, "no_override", person_id, 1, 0),
            ]
        )
        # Only one has an override
        insert_override_records([(self.team.id, "has_override", person_id, 1, 0)])

        # Query for missing overrides by distinct_id
        result = get_missing_overrides_for_distinct_ids(self.team.id, ["has_override", "no_override"])

        # Should return only the one without an override
        assert len(result) == 1
        assert result[0][0] == "no_override"
        assert result[0][1] == str(person_id)

    def test_returns_correct_person_id_from_pdi2(self):
        """Verify we get the person_id from pdi2, not from some other source."""
        pdi2_person_id = uuid4()

        # pdi2 says distinct_id maps to pdi2_person_id
        insert_pdi2_records([(self.team.id, "test_user", pdi2_person_id, 1, 0)])

        result = get_missing_overrides_for_distinct_ids(self.team.id, ["test_user"])

        assert len(result) == 1
        assert result[0][0] == "test_user"
        assert result[0][1] == str(pdi2_person_id)


class TestIntegration(ClickhouseTestMixin, BaseTest):
    def test_full_flow_creates_correct_override(self):
        """
        Integration test: verify that chaining get_mismatched_distinct_ids and
        get_missing_overrides_for_distinct_ids produces the correct override.

        Scenario: Event was written with OLD person_id, then pdi2 was updated to NEW person_id,
        but no override was created. The job should create an override pointing to NEW.
        """
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 says distinct_id -> NEW person_id (this is the source of truth after merge)
        insert_pdi2_records([(self.team.id, "merged_user", new_person_id, 2, 0)])

        # Event was written with OLD person_id (before the merge)
        # No override exists, so person_id on event stays as OLD
        _create_event(
            event="old_event",
            distinct_id="merged_user",
            person_id=str(old_person_id),
            team=self.team,
        )
        flush_persons_and_events()

        # Step 1: Find mismatched distinct_ids
        # person_id (OLD, from event) != pdi.person_id (NEW, from pdi2)
        mismatched = get_mismatched_distinct_ids(self.team)
        assert len(mismatched) == 1
        assert mismatched[0] == "merged_user"

        # Step 2: Get missing overrides for those distinct_ids
        missing = get_missing_overrides_for_distinct_ids(self.team.id, mismatched)
        assert len(missing) == 1
        distinct_id, person_id, version = missing[0]

        # The override should point to NEW person_id (from pdi2), not OLD
        assert distinct_id == "merged_user"
        assert person_id == str(new_person_id)

        # Step 3: Insert the override
        insert_override_batch([(self.team.id, distinct_id, person_id, max(version, 1))])

        # Verify the override was created correctly
        override = get_existing_override(self.team.id, "merged_user")
        assert override is not None
        assert override[0] == str(new_person_id)


class TestFixMissingPersonOverridesJob(ClickhouseTestMixin, BaseTest):
    def test_inserts_overrides_for_mismatched_distinct_ids(self):
        """Job inserts overrides for distinct_ids where event person_id != pdi2 person_id."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 says distinct_id -> NEW person_id (source of truth after merge)
        insert_pdi2_records([(self.team.id, "job_test_user", new_person_id, 2, 0)])

        # Event was written with OLD person_id (before the merge)
        _create_event(
            event="test_event",
            distinct_id="job_test_user",
            person_id=str(old_person_id),
            team=self.team,
        )
        flush_persons_and_events()

        # Run the job with dry_run=False
        fix_missing_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_missing_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        # Verify override was created pointing to NEW person_id (from pdi2)
        overrides = get_all_overrides(self.team.id)
        override_dict = dict(overrides)

        assert "job_test_user" in override_dict
        assert override_dict["job_test_user"] == str(new_person_id)

    def test_dry_run_does_not_insert(self):
        """Job does not insert overrides when dry_run=True."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 says distinct_id -> NEW person_id
        insert_pdi2_records([(self.team.id, "dry_run_user", new_person_id, 2, 0)])

        # Event was written with OLD person_id
        _create_event(
            event="test_event",
            distinct_id="dry_run_user",
            person_id=str(old_person_id),
            team=self.team,
        )
        flush_persons_and_events()

        # Run the job with dry_run=True
        fix_missing_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_missing_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": True,
                        }
                    }
                }
            }
        )

        # Verify no override was created
        overrides = get_all_overrides(self.team.id)
        assert len(overrides) == 0

    def test_skips_distinct_ids_with_existing_overrides(self):
        """Job does not insert overrides for distinct_ids that already have one."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 says both distinct_ids -> NEW person_id
        insert_pdi2_records(
            [
                (self.team.id, "has_override", new_person_id, 2, 0),
                (self.team.id, "no_override", new_person_id, 2, 0),
            ]
        )

        # One already has an override
        insert_override_records([(self.team.id, "has_override", new_person_id, 2, 0)])

        # Events for both were written with OLD person_id
        _create_event(
            event="test_event",
            distinct_id="has_override",
            person_id=str(old_person_id),
            team=self.team,
        )
        _create_event(
            event="test_event",
            distinct_id="no_override",
            person_id=str(old_person_id),
            team=self.team,
        )
        flush_persons_and_events()

        # Run the job
        fix_missing_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_missing_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        # Verify only the missing override was created
        overrides = get_all_overrides(self.team.id)
        override_dict = dict(overrides)

        assert len(overrides) == 2
        assert "has_override" in override_dict
        assert "no_override" in override_dict
        assert override_dict["no_override"] == str(new_person_id)
