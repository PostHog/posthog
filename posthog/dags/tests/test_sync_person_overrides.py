from datetime import datetime
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.dags.sync_person_overrides import (
    get_existing_override,
    get_mismatched_person_ids,
    insert_override_batch,
    sync_person_overrides_job,
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


class TestGetMismatchedPersonIds(ClickhouseTestMixin, BaseTest):
    def test_finds_person_ids_where_override_differs_from_pdi2(self):
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

        # The HogQL query should find new_person_id (from override) as mismatched
        result = get_mismatched_person_ids(self.team)

        assert len(result) == 1
        assert result[0] == str(new_person_id)

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

        result = get_mismatched_person_ids(self.team)

        assert len(result) == 0

    def test_returns_empty_when_no_events_exist(self):
        """When no events exist, no mismatches are found."""
        result = get_mismatched_person_ids(self.team)
        assert len(result) == 0


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


class TestSyncPersonOverridesJob(ClickhouseTestMixin, BaseTest):
    def test_inserts_missing_overrides_for_affected_persons(self):
        """When one distinct_id has an override, ensure all distinct_ids for that person get overrides."""
        old_person_id = uuid4()
        new_person_id = uuid4()

        # pdi2 has two distinct_ids mapping to old_person_id
        insert_pdi2_records(
            [
                (self.team.id, "user_with_override", old_person_id, 1, 0),
                (self.team.id, "user_without_override", old_person_id, 1, 0),
            ]
        )

        # pdi2 also has distinct_ids for new_person_id (the merge target)
        insert_pdi2_records(
            [
                (self.team.id, "original_user", new_person_id, 1, 0),
            ]
        )

        # Override exists only for one distinct_id
        insert_override_records([(self.team.id, "user_with_override", new_person_id, 1, 0)])

        # Create events to trigger the mismatch detection
        _create_event(event="test", distinct_id="user_with_override", team=self.team)
        flush_persons_and_events()

        # Run the job
        sync_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "sync_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        # All distinct_ids for new_person_id should now have overrides
        overrides = get_all_overrides(self.team.id)
        override_dict = dict(overrides)

        # user_with_override already had one
        assert override_dict.get("user_with_override") == str(new_person_id)
        # original_user should now have one too
        assert override_dict.get("original_user") == str(new_person_id)

    def test_does_nothing_when_no_mismatches(self):
        person_id = uuid4()

        insert_pdi2_records([(self.team.id, "normal_user", person_id, 1, 0)])

        _create_event(event="test", distinct_id="normal_user", team=self.team)
        flush_persons_and_events()

        result = sync_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "sync_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        assert result.success

        overrides = get_all_overrides(self.team.id)
        assert len(overrides) == 0

    def test_skips_distinct_ids_that_already_have_overrides(self):
        old_person_id = uuid4()
        new_person_id = uuid4()
        different_person_id = uuid4()

        insert_pdi2_records(
            [
                (self.team.id, "user_a", old_person_id, 1, 0),
                (self.team.id, "user_b", new_person_id, 1, 0),
            ]
        )

        # user_a has override to new_person_id (creates mismatch)
        insert_override_records([(self.team.id, "user_a", new_person_id, 1, 0)])
        # user_b already has an override to a different person
        insert_override_records([(self.team.id, "user_b", different_person_id, 1, 0)])

        _create_event(event="test", distinct_id="user_a", team=self.team)
        flush_persons_and_events()

        sync_person_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "sync_person_overrides_op": {
                        "config": {
                            "team_id": self.team.id,
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        overrides = get_all_overrides(self.team.id)
        override_dict = dict(overrides)

        # user_a should still point to new_person_id
        assert override_dict["user_a"] == str(new_person_id)
        # user_b should NOT be changed - it already had an override
        assert override_dict["user_b"] == str(different_person_id)
