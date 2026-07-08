from typing import Any

import pytest

from django.conf import settings

import psycopg

from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person, update_seed_person

# Sentinel team id used only by these tests. The seed helpers write through a raw
# psycopg connection that commits independently of Django's test transaction, so each
# test cleans up its own rows to avoid leaking into the shared persons test database.
SEED_TEST_TEAM_ID = 2_000_000_001

pytestmark = pytest.mark.django_db()


def _cleanup(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM posthog_persondistinctid WHERE team_id = %s", (SEED_TEST_TEAM_ID,))
        cursor.execute(f"DELETE FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s", (SEED_TEST_TEAM_ID,))


class TestPersonsSeedHelpers:
    def test_insert_person_persists_fields_and_sets_required_columns(self):
        with persons_db_connection(writer=True) as conn:
            try:
                person_id = insert_seed_person(
                    conn, team_id=SEED_TEST_TEAM_ID, properties={"email": "a@b.com"}, is_identified=True
                )
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT properties, is_identified, uuid, created_at FROM {settings.PERSON_TABLE_NAME} WHERE id = %s",
                        (person_id,),
                    )
                    row = cursor.fetchone()
                assert row is not None
                assert row[0] == {"email": "a@b.com"}
                assert row[1] is True
                assert row[2] is not None  # uuid filled (NOT NULL, no DB default)
                assert row[3] is not None  # created_at filled (NOT NULL, no DB default)
            finally:
                _cleanup(conn)

    def test_insert_distinct_id_links_to_person(self):
        with persons_db_connection(writer=True) as conn:
            try:
                person_id = insert_seed_person(conn, team_id=SEED_TEST_TEAM_ID, properties={})
                insert_seed_distinct_id(conn, team_id=SEED_TEST_TEAM_ID, person_id=person_id, distinct_id="seed-did")
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT person_id FROM posthog_persondistinctid WHERE team_id = %s AND distinct_id = %s",
                        (SEED_TEST_TEAM_ID, "seed-did"),
                    )
                    row = cursor.fetchone()
                assert row is not None
                assert row[0] == person_id
            finally:
                _cleanup(conn)

    def test_update_person_overwrites_properties_and_identified(self):
        with persons_db_connection(writer=True) as conn:
            try:
                person_uuid = "00000000-0000-0000-0000-000000000abc"
                insert_seed_person(
                    conn, team_id=SEED_TEST_TEAM_ID, properties={"v": 1}, is_identified=False, uuid=person_uuid
                )
                update_seed_person(
                    conn, team_id=SEED_TEST_TEAM_ID, uuid=person_uuid, properties={"v": 2}, is_identified=True
                )
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT properties, is_identified FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s AND uuid = %s",
                        (SEED_TEST_TEAM_ID, person_uuid),
                    )
                    row = cursor.fetchone()
                assert row is not None
                assert row[0] == {"v": 2}
                assert row[1] is True
            finally:
                _cleanup(conn)
