from datetime import datetime
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.dags.fix_missing_person_overrides import (
    get_existing_override,
    get_mismatched_person_ids,
    get_missing_overrides_for_person_ids,
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


class TestGetMissingOverridesForPersonIds(ClickhouseTestMixin, BaseTest):
    def test_returns_empty_for_empty_person_ids(self):
        result = get_missing_overrides_for_person_ids(self.team.id, [])
        assert len(result) == 0

    def test_returns_empty_for_nonexistent_person_id(self):
        result = get_missing_overrides_for_person_ids(self.team.id, [str(uuid4())])
        assert len(result) == 0

    def test_returns_missing_overrides(self):
        person_id = uuid4()

        insert_pdi2_records(
            [
                (self.team.id, "has_override", person_id, 1, 0),
                (self.team.id, "no_override", person_id, 1, 0),
            ]
        )
        insert_override_records([(self.team.id, "has_override", person_id, 1, 0)])

        result = get_missing_overrides_for_person_ids(self.team.id, [str(person_id)])

        assert len(result) == 1
        assert result[0][0] == "no_override"
