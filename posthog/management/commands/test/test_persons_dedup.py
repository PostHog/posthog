from __future__ import annotations

import json
import uuid as uuid_mod
from typing import Any

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

import psycopg

from posthog.persons_db import persons_db_connection

pytestmark = pytest.mark.django_db

TEAM = 987654

# The test database is built from rust/persons_migrations, which declares
# posthog_person_new_uuid_idx as UNIQUE. Production does not have it -- that divergence
# is the entire reason this command exists, and it means the test database physically
# rejects the duplicate rows we need to seed. Recreate the index non-unique so the
# fixture holds what production holds, and restore it afterwards.
DROP_UNIQUE_UUID_INDEX = "DROP INDEX IF EXISTS posthog_person_new_uuid_idx"
CREATE_NON_UNIQUE_UUID_INDEX = "CREATE INDEX posthog_person_new_uuid_idx ON posthog_person (team_id, uuid)"
RESTORE_UNIQUE_UUID_INDEX = "CREATE UNIQUE INDEX posthog_person_new_uuid_idx ON posthog_person (team_id, uuid)"

# Production also carries foreign keys that rust/persons_migrations does NOT declare,
# and their ON DELETE behaviour is what makes this command dangerous or safe. Without
# recreating that drift here every safety assertion below would pass vacuously.
PROD_FK_DRIFT = [
    (
        "posthog_persondistinctid",
        "test_pdi_person_fk",
        "FOREIGN KEY (team_id, person_id) REFERENCES posthog_person(team_id, id) NOT VALID",
    ),
    (
        "posthog_featureflaghashkeyoverride",
        "test_ff_person_fk",
        "FOREIGN KEY (team_id, person_id) REFERENCES posthog_person(team_id, id) ON DELETE CASCADE NOT VALID",
    ),
]


def _uuid(n: int) -> str:
    return str(uuid_mod.UUID(int=n))


@pytest.fixture
def persons_conn():
    with persons_db_connection(writer=True, autocommit=True) as conn:
        _cleanup(conn)
        with conn.cursor() as cur:
            cur.execute(DROP_UNIQUE_UUID_INDEX)
            cur.execute(CREATE_NON_UNIQUE_UUID_INDEX)
        for table, name, definition in PROD_FK_DRIFT:
            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
                cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")
        try:
            yield conn
        finally:
            for table, name, _ in PROD_FK_DRIFT:
                with conn.cursor() as cur:
                    cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
            _cleanup(conn)
            with conn.cursor() as cur:
                cur.execute(DROP_UNIQUE_UUID_INDEX)
                cur.execute(RESTORE_UNIQUE_UUID_INDEX)


def _cleanup(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = %s", (TEAM,))
        cur.execute(
            "DELETE FROM posthog_cohortpeople WHERE person_id IN (SELECT id FROM posthog_person WHERE team_id = %s)",
            (TEAM,),
        )
        cur.execute("DELETE FROM posthog_persondistinctid WHERE team_id = %s", (TEAM,))
        cur.execute("DELETE FROM posthog_person WHERE team_id = %s", (TEAM,))


def _add_person(conn: psycopg.Connection, uuid: str, *, properties: str = "{}", version: int = 0) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_person (created_at, properties, team_id, is_identified, uuid, version) "
            "VALUES (now(), %s::jsonb, %s, false, %s, %s) RETURNING id",
            (properties, TEAM, uuid, version),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _add_distinct_id(conn: psycopg.Connection, person_id: int, distinct_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version) VALUES (%s, %s, %s, 0)",
            (TEAM, person_id, distinct_id),
        )


def _add_flag_override(conn: psycopg.Connection, person_id: int, key: str, hash_key: str = "h") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) "
            "VALUES (%s, %s, %s, %s)",
            (TEAM, person_id, key, hash_key),
        )


def _count(conn: psycopg.Connection, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _persons(conn: psycopg.Connection) -> int:
    return _count(conn, "SELECT count(*) FROM posthog_person WHERE team_id = %s", (TEAM,))


def _flag_overrides(conn: psycopg.Connection) -> int:
    return _count(conn, "SELECT count(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = %s", (TEAM,))


def _distinct_ids(conn: psycopg.Connection) -> int:
    return _count(conn, "SELECT count(*) FROM posthog_persondistinctid WHERE team_id = %s", (TEAM,))


def _dup_groups(conn: psycopg.Connection) -> int:
    return _count(
        conn,
        "SELECT count(*) FROM (SELECT uuid FROM posthog_person WHERE team_id = %s GROUP BY uuid HAVING count(*) > 1) x",
        (TEAM,),
    )


def _run(mode: str, tmp_path: Any, **kwargs: Any) -> None:
    call_command("persons_dedup", mode=mode, team=TEAM, outdir=str(tmp_path), **kwargs)


class TestPersonsDedupFixture:
    def test_fixture_reproduces_the_production_cascade(self, persons_conn, tmp_path):
        # Guards the fixture itself. If the prod FK drift is ever reconciled into
        # rust/persons_migrations and this ALTER stops matching production, every safety
        # test below would silently start passing for the wrong reason.
        person = _add_person(persons_conn, _uuid(1))
        _add_flag_override(persons_conn, person, "flag-a")
        assert _flag_overrides(persons_conn) == 1

        with persons_conn.cursor() as cur:
            cur.execute("DELETE FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, person))

        assert _flag_overrides(persons_conn) == 0, "prod FK is ON DELETE CASCADE; fixture must reproduce it"

    def test_fixture_reproduces_the_missing_unique_index(self, persons_conn, tmp_path):
        # The whole defect: production allows two rows to share (team_id, uuid). The
        # tracked migrations declare that index UNIQUE, so if this fixture ever stops
        # recreating it non-unique, every duplicate scenario below becomes unseedable
        # and the suite would fail loudly rather than pass vacuously.
        uuid = _uuid(3)
        _add_person(persons_conn, uuid)
        _add_person(persons_conn, uuid)

        assert _dup_groups(persons_conn) == 1

    def test_fixture_reproduces_the_production_delete_block(self, persons_conn, tmp_path):
        person = _add_person(persons_conn, _uuid(2))
        _add_distinct_id(persons_conn, person, "did-block")

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with persons_conn.cursor() as cur:
                cur.execute("DELETE FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, person))


class TestPersonsDedupDeleteOnly:
    def test_deletes_unreferenced_duplicate_and_keeps_the_live_row(self, persons_conn, tmp_path):
        uuid = _uuid(10)
        orphan = _add_person(persons_conn, uuid, properties='{"email": "keep"}')
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-10")

        _run("plan", tmp_path, apply=True)

        assert _dup_groups(persons_conn) == 0
        assert _persons(persons_conn) == 1
        assert _distinct_ids(persons_conn) == 1
        remaining = _count(persons_conn, "SELECT id FROM posthog_person WHERE team_id = %s", (TEAM,))
        assert remaining == live, "the row owning the distinct id must survive, not the orphan"
        assert orphan != live

    def test_refuses_to_delete_a_referenced_row(self, persons_conn, tmp_path):
        # Both rows own a distinct ID, so neither is unreachable. Nothing may be removed.
        uuid = _uuid(11)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-11a")
        _add_distinct_id(persons_conn, b, "did-11b")

        _run("plan", tmp_path, apply=True)

        assert _persons(persons_conn) == 2
        assert _dup_groups(persons_conn) == 1

    def test_dry_run_writes_nothing(self, persons_conn, tmp_path):
        uuid = _uuid(12)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-12")

        _run("plan", tmp_path)

        assert _persons(persons_conn) == 2
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_backup_captures_deleted_person_properties(self, persons_conn, tmp_path):
        uuid = _uuid(13)
        _add_person(persons_conn, uuid, properties='{"email": "gone"}')
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-13")

        _run("plan", tmp_path, apply=True)

        lines = [line for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        persons = [json.loads(line) for line in lines]
        assert any(p["_kind"] == "person" and p["properties"] == {"email": "gone"} for p in persons)

    def test_is_idempotent(self, persons_conn, tmp_path):
        uuid = _uuid(14)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-14")

        _run("plan", tmp_path, apply=True)
        _run("plan", tmp_path, apply=True)

        assert _persons(persons_conn) == 1


class TestPersonsDedupRepair:
    def test_repairs_the_production_shape(self, persons_conn, tmp_path):
        # The shape of all 2,150 merge-required groups measured in prod-EU team 71093:
        # one row owns the distinct ID, the other owns a flag override, neither owns both.
        uuid = _uuid(20)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-20")
        stranded = _add_person(persons_conn, uuid)
        _add_flag_override(persons_conn, stranded, "flag-20")

        _run("repair", tmp_path, apply=True)

        assert _dup_groups(persons_conn) == 0
        assert _persons(persons_conn) == 1
        assert _distinct_ids(persons_conn) == 1
        # The stranded row's override was unreachable (no distinct ID resolves to it),
        # so cascading it away preserves behaviour. Moving it onto the live person would
        # instead resurrect dead data and could change that user's flag variant.
        assert _flag_overrides(persons_conn) == 0

    def test_survivor_is_the_distinct_id_owner_even_when_it_is_the_newer_row(self, persons_conn, tmp_path):
        # Production's actual shape: the distinct id points at the NEWER row in every
        # measured group, and the stranded older row is the one carrying the override.
        # Ranking must prefer the distinct-id owner, not the oldest or lowest id --
        # picking the wrong survivor would delete the row the product can still reach.
        uuid = _uuid(24)
        stranded = _add_person(persons_conn, uuid)
        _add_flag_override(persons_conn, stranded, "flag-24")
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-24")

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        survivor = _count(persons_conn, "SELECT id FROM posthog_person WHERE team_id = %s", (TEAM,))
        assert survivor == live, "the row owning the distinct id must survive even when it is newer"
        assert _distinct_ids(persons_conn) == 1

    def test_leaves_a_reachable_override_alone(self, persons_conn, tmp_path):
        # Same shape, except the override sits on the row that owns the distinct ID, so
        # it IS reachable and must survive untouched.
        uuid = _uuid(21)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-21")
        _add_flag_override(persons_conn, live, "flag-21")
        _add_person(persons_conn, uuid)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        assert _flag_overrides(persons_conn) == 1

    def test_refuses_groups_where_two_rows_own_distinct_ids(self, persons_conn, tmp_path):
        uuid = _uuid(22)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-22a")
        _add_distinct_id(persons_conn, b, "did-22b")
        _add_flag_override(persons_conn, b, "flag-22")

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 2
        assert _flag_overrides(persons_conn) == 1

    def test_backup_captures_cascaded_flag_overrides(self, persons_conn, tmp_path):
        uuid = _uuid(23)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-23")
        stranded = _add_person(persons_conn, uuid)
        _add_flag_override(persons_conn, stranded, "flag-23", hash_key="hk-23")

        _run("repair", tmp_path, apply=True)

        lines = [line for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        records = [json.loads(line) for line in lines]
        assert any(
            r["_kind"] == "featureflaghashkeyoverride" and r["key"] == "flag-23" and r["value"] == "hk-23"
            for r in records
        ), "a cascaded override must be recoverable from the backup"


class TestPersonsDedupVerify:
    def test_verify_fails_while_duplicates_remain(self, persons_conn, tmp_path):
        uuid = _uuid(30)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-30a")
        _add_distinct_id(persons_conn, b, "did-30b")

        with pytest.raises(CommandError, match="duplicate group"):
            _run("verify", tmp_path)

    def test_verify_passes_once_clean(self, persons_conn, tmp_path):
        person = _add_person(persons_conn, _uuid(31))
        _add_distinct_id(persons_conn, person, "did-31")

        _run("verify", tmp_path)

    def test_apply_is_rejected_for_read_only_modes(self, persons_conn, tmp_path):
        with pytest.raises(CommandError, match="meaningless"):
            _run("verify", tmp_path, apply=True)
