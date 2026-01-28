from datetime import datetime
from uuid import UUID

import pytest

from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.fix_person_id_overrides import (
    fix_person_id_overrides_job,
    get_all_distinct_ids_for_person,
    get_existing_override,
    get_person_id_from_pdi2,
    insert_override,
)

TEAM_ID = 1


def insert_pdi2_records(client: Client, records: list[tuple[int, str, UUID, int, int]]) -> None:
    """Insert records into person_distinct_id2: (team_id, distinct_id, person_id, version, is_deleted)"""
    client.execute(
        "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, version, is_deleted) VALUES",
        records,
    )


def insert_override_records(client: Client, records: list[tuple[int, str, UUID, int, int]]) -> None:
    """Insert records into person_distinct_id_overrides: (team_id, distinct_id, person_id, version, is_deleted)"""
    client.execute(
        "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted, _timestamp, _offset, _partition) VALUES",
        [(r[0], r[1], r[2], r[3], r[4], datetime(2025, 1, 1), 0, 0) for r in records],
    )


def get_all_overrides(client: Client, team_id: int) -> list[tuple[str, str]]:
    """Get all overrides for a team: (distinct_id, person_id)"""
    result = client.execute(
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


class TestGetPersonIdFromPdi2:
    @pytest.mark.django_db
    def test_returns_person_id_and_version(self, cluster: ClickhouseCluster):
        person_id = UUID(int=1)

        def setup(client: Client) -> None:
            insert_pdi2_records(client, [(TEAM_ID, "user_123", person_id, 1, 0)])

        cluster.any_host(setup).result()

        result = get_person_id_from_pdi2(TEAM_ID, "user_123")

        assert result is not None
        assert result[0] == str(person_id)
        assert result[1] == 1

    @pytest.mark.django_db
    def test_returns_none_for_missing_distinct_id(self, cluster: ClickhouseCluster):
        result = get_person_id_from_pdi2(TEAM_ID, "nonexistent")
        assert result is None

    @pytest.mark.django_db
    def test_returns_none_for_deleted_mapping(self, cluster: ClickhouseCluster):
        person_id = UUID(int=2)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "deleted_user", person_id, 1, 0),
                    (TEAM_ID, "deleted_user", person_id, 2, 1),  # deleted
                ],
            )

        cluster.any_host(setup).result()

        result = get_person_id_from_pdi2(TEAM_ID, "deleted_user")
        assert result is None

    @pytest.mark.django_db
    def test_returns_latest_person_id_by_version(self, cluster: ClickhouseCluster):
        old_person_id = UUID(int=10)
        new_person_id = UUID(int=20)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "merged_user", old_person_id, 1, 0),
                    (TEAM_ID, "merged_user", new_person_id, 2, 0),  # newer version
                ],
            )

        cluster.any_host(setup).result()

        result = get_person_id_from_pdi2(TEAM_ID, "merged_user")

        assert result is not None
        assert result[0] == str(new_person_id)
        assert result[1] == 2


class TestGetAllDistinctIdsForPerson:
    @pytest.mark.django_db
    def test_returns_all_distinct_ids_for_person(self, cluster: ClickhouseCluster):
        person_id = UUID(int=100)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "anon_id", person_id, 1, 0),
                    (TEAM_ID, "email@example.com", person_id, 1, 0),
                    (TEAM_ID, "phone_123", person_id, 1, 0),
                ],
            )

        cluster.any_host(setup).result()

        result = get_all_distinct_ids_for_person(TEAM_ID, str(person_id))

        distinct_ids = {did for did, _ in result}
        assert distinct_ids == {"anon_id", "email@example.com", "phone_123"}

    @pytest.mark.django_db
    def test_excludes_deleted_mappings(self, cluster: ClickhouseCluster):
        person_id = UUID(int=101)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "active_id", person_id, 1, 0),
                    (TEAM_ID, "deleted_id", person_id, 1, 0),
                    (TEAM_ID, "deleted_id", person_id, 2, 1),  # deleted
                ],
            )

        cluster.any_host(setup).result()

        result = get_all_distinct_ids_for_person(TEAM_ID, str(person_id))

        distinct_ids = {did for did, _ in result}
        assert distinct_ids == {"active_id"}

    @pytest.mark.django_db
    def test_returns_empty_for_nonexistent_person(self, cluster: ClickhouseCluster):
        result = get_all_distinct_ids_for_person(TEAM_ID, str(UUID(int=999)))
        assert result == []


class TestGetExistingOverride:
    @pytest.mark.django_db
    def test_returns_override_when_exists(self, cluster: ClickhouseCluster):
        person_id = UUID(int=200)

        def setup(client: Client) -> None:
            insert_override_records(client, [(TEAM_ID, "override_user", person_id, 1, 0)])

        cluster.any_host(setup).result()

        result = get_existing_override(TEAM_ID, "override_user")

        assert result is not None
        assert result[0] == str(person_id)
        assert result[1] == 1

    @pytest.mark.django_db
    def test_returns_none_when_no_override(self, cluster: ClickhouseCluster):
        result = get_existing_override(TEAM_ID, "no_override_user")
        assert result is None

    @pytest.mark.django_db
    def test_returns_none_for_deleted_override(self, cluster: ClickhouseCluster):
        person_id = UUID(int=201)

        def setup(client: Client) -> None:
            insert_override_records(
                client,
                [
                    (TEAM_ID, "deleted_override", person_id, 1, 0),
                    (TEAM_ID, "deleted_override", person_id, 2, 1),  # deleted
                ],
            )

        cluster.any_host(setup).result()

        result = get_existing_override(TEAM_ID, "deleted_override")
        assert result is None


class TestInsertOverride:
    @pytest.mark.django_db
    def test_inserts_override_record(self, cluster: ClickhouseCluster):
        person_id = UUID(int=300)

        insert_override(TEAM_ID, "new_override", str(person_id), 1)

        result = get_existing_override(TEAM_ID, "new_override")
        assert result is not None
        assert result[0] == str(person_id)


class TestFixPersonIdOverridesJob:
    @pytest.mark.django_db
    def test_inserts_overrides_for_all_distinct_ids_of_person(self, cluster: ClickhouseCluster):
        person_id = UUID(int=400)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "anon_abc123", person_id, 1, 0),
                    (TEAM_ID, "user@email.com", person_id, 1, 0),
                ],
            )

        cluster.any_host(setup).result()

        fix_person_id_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_person_id_overrides_op": {
                        "config": {
                            "team_id": TEAM_ID,
                            "distinct_ids": "anon_abc123",
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        overrides = cluster.any_host(lambda c: get_all_overrides(c, TEAM_ID)).result()
        override_dict = dict(overrides)

        assert "anon_abc123" in override_dict
        assert "user@email.com" in override_dict
        assert override_dict["anon_abc123"] == str(person_id)
        assert override_dict["user@email.com"] == str(person_id)

    @pytest.mark.django_db
    def test_dry_run_does_not_insert(self, cluster: ClickhouseCluster):
        person_id = UUID(int=401)

        def setup(client: Client) -> None:
            insert_pdi2_records(client, [(TEAM_ID, "dry_run_user", person_id, 1, 0)])

        cluster.any_host(setup).result()

        fix_person_id_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_person_id_overrides_op": {
                        "config": {
                            "team_id": TEAM_ID,
                            "distinct_ids": "dry_run_user",
                            "dry_run": True,
                        }
                    }
                }
            }
        )

        overrides = cluster.any_host(lambda c: get_all_overrides(c, TEAM_ID)).result()
        assert len(overrides) == 0

    @pytest.mark.django_db
    def test_skips_existing_overrides(self, cluster: ClickhouseCluster):
        person_id = UUID(int=402)
        existing_person_id = UUID(int=403)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "existing_override_user", person_id, 1, 0),
                    (TEAM_ID, "new_user", person_id, 1, 0),
                ],
            )
            insert_override_records(client, [(TEAM_ID, "existing_override_user", existing_person_id, 1, 0)])

        cluster.any_host(setup).result()

        fix_person_id_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_person_id_overrides_op": {
                        "config": {
                            "team_id": TEAM_ID,
                            "distinct_ids": "existing_override_user",
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        overrides = cluster.any_host(lambda c: get_all_overrides(c, TEAM_ID)).result()
        override_dict = dict(overrides)

        # Existing override should not be changed
        assert override_dict["existing_override_user"] == str(existing_person_id)
        # New user should have override inserted
        assert override_dict["new_user"] == str(person_id)

    @pytest.mark.django_db
    def test_handles_multiple_distinct_ids_mapping_to_same_person(self, cluster: ClickhouseCluster):
        person_id = UUID(int=404)

        def setup(client: Client) -> None:
            insert_pdi2_records(
                client,
                [
                    (TEAM_ID, "id_a", person_id, 1, 0),
                    (TEAM_ID, "id_b", person_id, 1, 0),
                    (TEAM_ID, "id_c", person_id, 1, 0),
                ],
            )

        cluster.any_host(setup).result()

        # Pass multiple distinct_ids that map to the same person
        fix_person_id_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_person_id_overrides_op": {
                        "config": {
                            "team_id": TEAM_ID,
                            "distinct_ids": "id_a,id_b",
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        overrides = cluster.any_host(lambda c: get_all_overrides(c, TEAM_ID)).result()
        override_dict = dict(overrides)

        # All three should have overrides (even id_c which wasn't in the input)
        assert len(override_dict) == 3
        assert all(v == str(person_id) for v in override_dict.values())

    @pytest.mark.django_db
    def test_handles_nonexistent_distinct_id(self, cluster: ClickhouseCluster):
        # Should complete without error
        result = fix_person_id_overrides_job.execute_in_process(
            run_config={
                "ops": {
                    "fix_person_id_overrides_op": {
                        "config": {
                            "team_id": TEAM_ID,
                            "distinct_ids": "nonexistent_id",
                            "dry_run": False,
                        }
                    }
                }
            }
        )

        assert result.success
