from typing import Any

import pytest

from django.conf import settings

import psycopg

from posthog.persons_db import persons_db_connection

from products.demo.backend.logic.matrix.persons_db_sync import (
    _insert_groups,
    _insert_person_distinct_ids,
    _insert_persons,
    bulk_create_group_type_mappings,
    copy_group_type_mappings,
    delete_group_type_mappings,
    get_group_type_mapping_count,
)

SYNC_TEST_TEAM_ID = 2_000_000_010
SYNC_TEST_PROJECT_ID = 2_000_000_010
SYNC_TEST_TARGET_TEAM_ID = 2_000_000_011
SYNC_TEST_TARGET_PROJECT_ID = 2_000_000_011

pytestmark = pytest.mark.django_db()


def _cleanup(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        for team_id in (SYNC_TEST_TEAM_ID, SYNC_TEST_TARGET_TEAM_ID):
            cur.execute("DELETE FROM posthog_persondistinctid WHERE team_id = %s", (team_id,))
            cur.execute(f"DELETE FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s", (team_id,))
            cur.execute("DELETE FROM posthog_group WHERE team_id = %s", (team_id,))
        for project_id in (SYNC_TEST_PROJECT_ID, SYNC_TEST_TARGET_PROJECT_ID):
            cur.execute("DELETE FROM posthog_grouptypemapping WHERE project_id = %s", (project_id,))


class TestInsertPersons:
    def test_inserts_persons_and_returns_uuid_to_pk_mapping(self):
        with persons_db_connection(writer=True) as conn:
            try:
                with conn.cursor() as cur:
                    uuid_to_pk = _insert_persons(
                        cur,
                        [
                            {
                                "uuid": "00000000-0000-0000-0000-000000000001",
                                "properties": '{"email": "a@b.com"}',
                                "is_identified": True,
                                "created_at": "2024-01-01T00:00:00Z",
                                "version": 0,
                                "last_seen_at": None,
                            },
                            {
                                "uuid": "00000000-0000-0000-0000-000000000002",
                                "properties": {"name": "Test"},
                                "is_identified": False,
                                "created_at": "2024-01-02T00:00:00Z",
                                "version": 1,
                                "last_seen_at": None,
                            },
                        ],
                        SYNC_TEST_TEAM_ID,
                        settings.PERSON_TABLE_NAME,
                    )

                assert len(uuid_to_pk) == 2
                assert "00000000-0000-0000-0000-000000000001" in uuid_to_pk
                assert "00000000-0000-0000-0000-000000000002" in uuid_to_pk
                assert isinstance(uuid_to_pk["00000000-0000-0000-0000-000000000001"], int)

                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT uuid, properties, is_identified FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s ORDER BY uuid",
                        (SYNC_TEST_TEAM_ID,),
                    )
                    rows = cur.fetchall()
                assert len(rows) == 2
                assert rows[0][1] == {"email": "a@b.com"}
                assert rows[0][2] is True
                assert rows[1][1] == {"name": "Test"}
                assert rows[1][2] is False
            finally:
                _cleanup(conn)

    def test_empty_list_returns_empty_dict(self):
        with persons_db_connection(writer=True) as conn:
            with conn.cursor() as cur:
                result = _insert_persons(cur, [], SYNC_TEST_TEAM_ID, settings.PERSON_TABLE_NAME)
            assert result == {}


class TestInsertPersonDistinctIds:
    def test_inserts_distinct_ids_linked_to_persons(self):
        with persons_db_connection(writer=True) as conn:
            try:
                with conn.cursor() as cur:
                    uuid_to_pk = _insert_persons(
                        cur,
                        [
                            {
                                "uuid": "00000000-0000-0000-0000-000000000010",
                                "properties": "{}",
                                "is_identified": False,
                                "created_at": "2024-01-01T00:00:00Z",
                                "version": 0,
                                "last_seen_at": None,
                            },
                        ],
                        SYNC_TEST_TEAM_ID,
                        settings.PERSON_TABLE_NAME,
                    )

                    _insert_person_distinct_ids(
                        cur,
                        [
                            {
                                "person_uuid": "00000000-0000-0000-0000-000000000010",
                                "distinct_id": "user-abc",
                                "version": 0,
                            },
                        ],
                        SYNC_TEST_TEAM_ID,
                        uuid_to_pk,
                    )

                    cur.execute(
                        "SELECT distinct_id, person_id FROM posthog_persondistinctid WHERE team_id = %s",
                        (SYNC_TEST_TEAM_ID,),
                    )
                    rows = cur.fetchall()
                assert len(rows) == 1
                assert rows[0][0] == "user-abc"
                assert rows[0][1] == uuid_to_pk["00000000-0000-0000-0000-000000000010"]
            finally:
                _cleanup(conn)

    def test_skips_distinct_ids_with_unknown_person_uuid(self):
        with persons_db_connection(writer=True) as conn:
            try:
                with conn.cursor() as cur:
                    _insert_person_distinct_ids(
                        cur,
                        [{"person_uuid": "nonexistent-uuid", "distinct_id": "orphan", "version": 0}],
                        SYNC_TEST_TEAM_ID,
                        {},
                    )
                    cur.execute(
                        "SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = %s",
                        (SYNC_TEST_TEAM_ID,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert row[0] == 0
            finally:
                _cleanup(conn)


class TestInsertGroups:
    def test_inserts_groups_with_properties(self):
        with persons_db_connection(writer=True) as conn:
            try:
                with conn.cursor() as cur:
                    _insert_groups(
                        cur,
                        [
                            {
                                "group_type_index": 0,
                                "group_key": "acme-inc",
                                "group_properties": '{"name": "Acme"}',
                                "created_at": "2024-01-01T00:00:00Z",
                            },
                        ],
                        SYNC_TEST_TEAM_ID,
                    )

                    cur.execute(
                        "SELECT group_key, group_properties, group_type_index FROM posthog_group WHERE team_id = %s",
                        (SYNC_TEST_TEAM_ID,),
                    )
                    rows = cur.fetchall()
                assert len(rows) == 1
                assert rows[0][0] == "acme-inc"
                assert rows[0][1] == {"name": "Acme"}
                assert rows[0][2] == 0
            finally:
                _cleanup(conn)


class TestGroupTypeMappingHelpers:
    def test_bulk_create_and_count(self):
        try:
            bulk_create_group_type_mappings(
                SYNC_TEST_TEAM_ID,
                SYNC_TEST_PROJECT_ID,
                [
                    {"group_type_index": 0, "group_type": "company"},
                    {"group_type_index": 1, "group_type": "project"},
                ],
            )

            assert get_group_type_mapping_count(SYNC_TEST_PROJECT_ID) == 2
        finally:
            with persons_db_connection(writer=True) as conn:
                _cleanup(conn)

    def test_delete_removes_mappings(self):
        try:
            bulk_create_group_type_mappings(
                SYNC_TEST_TEAM_ID,
                SYNC_TEST_PROJECT_ID,
                [{"group_type_index": 0, "group_type": "company"}],
            )
            assert get_group_type_mapping_count(SYNC_TEST_PROJECT_ID) == 1

            delete_group_type_mappings(SYNC_TEST_PROJECT_ID)
            assert get_group_type_mapping_count(SYNC_TEST_PROJECT_ID) == 0
        finally:
            with persons_db_connection(writer=True) as conn:
                _cleanup(conn)

    def test_copy_transfers_mappings_between_projects(self):
        try:
            bulk_create_group_type_mappings(
                SYNC_TEST_TEAM_ID,
                SYNC_TEST_PROJECT_ID,
                [
                    {"group_type_index": 0, "group_type": "company", "name_singular": "Company"},
                    {"group_type_index": 1, "group_type": "team"},
                ],
            )

            copy_group_type_mappings(SYNC_TEST_PROJECT_ID, SYNC_TEST_TARGET_TEAM_ID, SYNC_TEST_TARGET_PROJECT_ID)

            assert get_group_type_mapping_count(SYNC_TEST_TARGET_PROJECT_ID) == 2

            with persons_db_connection(writer=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT team_id, group_type, name_singular FROM posthog_grouptypemapping "
                        "WHERE project_id = %s ORDER BY group_type_index",
                        (SYNC_TEST_TARGET_PROJECT_ID,),
                    )
                    rows = cur.fetchall()
            assert rows[0][0] == SYNC_TEST_TARGET_TEAM_ID
            assert rows[0][1] == "company"
            assert rows[0][2] == "Company"
            assert rows[1][1] == "team"
        finally:
            with persons_db_connection(writer=True) as conn:
                _cleanup(conn)

    def test_bulk_create_handles_integrity_error_gracefully(self):
        try:
            bulk_create_group_type_mappings(
                SYNC_TEST_TEAM_ID,
                SYNC_TEST_PROJECT_ID,
                [{"group_type_index": 0, "group_type": "company"}],
            )
            bulk_create_group_type_mappings(
                SYNC_TEST_TEAM_ID,
                SYNC_TEST_PROJECT_ID,
                [{"group_type_index": 0, "group_type": "company"}],
            )
            assert get_group_type_mapping_count(SYNC_TEST_PROJECT_ID) == 1
        finally:
            with persons_db_connection(writer=True) as conn:
                _cleanup(conn)
