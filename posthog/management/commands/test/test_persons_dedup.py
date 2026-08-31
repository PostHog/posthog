from __future__ import annotations

import re
import json
import uuid as uuid_mod
import logging
from contextlib import contextmanager
from typing import Any

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

import psycopg
from structlog.testing import capture_logs

from posthog.management.commands import persons_dedup as persons_dedup_command
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


def _add_person(
    conn: psycopg.Connection,
    uuid: str,
    *,
    properties: str = "{}",
    version: int = 0,
    is_identified: bool = False,
    is_deleted: bool = False,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_person "
            "(created_at, properties, team_id, is_identified, uuid, version, is_deleted) "
            "VALUES (now(), %s::jsonb, %s, %s, %s, %s, %s) RETURNING id",
            (properties, TEAM, is_identified, uuid, version, is_deleted),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


# One duplicate group: an unreferenced orphan plus the live row that must survive.
def _add_orphan_pair(conn: psycopg.Connection, uuid: str, distinct_id: str) -> int:
    _add_person(conn, uuid)
    live = _add_person(conn, uuid)
    _add_distinct_id(conn, live, distinct_id)
    return live


def _add_orphan_pair_ids(conn: psycopg.Connection, uuid: str, distinct_id: str) -> tuple[int, int]:
    orphan = _add_person(conn, uuid)
    live = _add_person(conn, uuid)
    _add_distinct_id(conn, live, distinct_id)
    return orphan, live


# Runs `action` on a second connection at the one moment that matters: after the command has
# cleared its pre-flight gates and before it opens the delete transaction. Every gate-failure
# path is unreachable without this, because staging excludes anything the gates would catch --
# only a concurrent writer can make a staged victim undeletable.
@contextmanager
def _concurrent_write_before_delete(monkeypatch, action):
    real_gates = persons_dedup_command._gates
    state = {"fired": False}

    def gates_then_interfere(conn):
        result = real_gates(conn)
        # The pre-flight is the first gate call and the in-transaction re-check is the second,
        # so firing after the first lands the write in the only window the gates can catch.
        if not state["fired"]:
            state["fired"] = True
            with persons_db_connection(writer=True, autocommit=True) as other:
                action(other)
        return result

    monkeypatch.setattr(persons_dedup_command, "_gates", gates_then_interfere)
    yield lambda: state["fired"]


def _add_distinct_id(conn: psycopg.Connection, person_id: int, distinct_id: str, *, is_deleted: bool = False) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version, is_deleted) "
            "VALUES (%s, %s, %s, 0, %s)",
            (TEAM, person_id, distinct_id, is_deleted),
        )


def _add_flag_override(conn: psycopg.Connection, person_id: int, key: str, hash_key: str = "h") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) "
            "VALUES (%s, %s, %s, %s)",
            (TEAM, person_id, key, hash_key),
        )


def _add_cohort_member(conn: psycopg.Connection, person_id: int, cohort_id: int = 4242) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_cohortpeople (cohort_id, person_id, version) VALUES (%s, %s, 0)",
            (cohort_id, person_id),
        )


def _cohort_rows(conn: psycopg.Connection) -> int:
    return _count(
        conn,
        "SELECT count(*) FROM posthog_cohortpeople WHERE person_id IN "
        "(SELECT id FROM posthog_person WHERE team_id = %s)",
        (TEAM,),
    )


def _orphaned_cohort_rows(conn: psycopg.Connection, cohort_id: int = 4242) -> int:
    return _count(
        conn,
        "SELECT count(*) FROM posthog_cohortpeople cp WHERE cp.cohort_id = %s "
        "AND NOT EXISTS (SELECT 1 FROM posthog_person p WHERE p.id = cp.person_id)",
        (cohort_id,),
    )


def _orphan_a_distinct_id(conn: psycopg.Connection, person_id: int) -> None:
    # Production's foreign keys are NOT VALID, so orphaned mappings predate them and a normal
    # insert cannot make one. session_replication_role = replica disables the FK triggers for this
    # session, which deletes the person out from under its mapping without dropping all 64
    # per-partition constraints. Needs a superuser, which the dev and CI Postgres role is.
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = 'replica'")
        try:
            cur.execute("DELETE FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, person_id))
        finally:
            cur.execute("SET session_replication_role = 'origin'")


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
    kwargs.setdefault("sleep_ms", 0)
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

        _run("delete-unreferenced", tmp_path, apply=True)

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

        _run("delete-unreferenced", tmp_path, apply=True)

        assert _persons(persons_conn) == 2
        assert _dup_groups(persons_conn) == 1

    def test_dry_run_writes_nothing(self, persons_conn, tmp_path):
        uuid = _uuid(12)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-12")

        _run("delete-unreferenced", tmp_path)

        assert _persons(persons_conn) == 2
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_backup_captures_deleted_person_properties(self, persons_conn, tmp_path):
        uuid = _uuid(13)
        _add_person(persons_conn, uuid, properties='{"email": "gone"}')
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-13")

        _run("delete-unreferenced", tmp_path, apply=True)

        lines = [line for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        persons = [json.loads(line) for line in lines]
        assert any(p["_kind"] == "person" and p["properties"] == {"email": "gone"} for p in persons)

    def test_backup_file_is_owner_only(self, persons_conn, tmp_path):
        # The backup holds person properties; on a shared pod filesystem a default-umask
        # 0644 file would expose them to any local account.
        uuid = _uuid(15)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-15")

        _run("delete-unreferenced", tmp_path, apply=True)

        files = list(tmp_path.glob("*.jsonl"))
        assert files, "apply must write a backup file"
        assert (files[0].stat().st_mode & 0o777) == 0o600

    def test_is_idempotent(self, persons_conn, tmp_path):
        uuid = _uuid(14)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-14")

        _run("delete-unreferenced", tmp_path, apply=True)
        _run("delete-unreferenced", tmp_path, apply=True)

        assert _persons(persons_conn) == 1


class TestPersonsDedupBatching:
    # Every other case here stages one or two victims against the default batch size of 500,
    # so the drain loop only ever runs once. A real team runs it hundreds of times, where a
    # bug in the take/retire cycle -- retiring the wrong rows, or not truncating the batch
    # table -- would strand most of that team while still reporting success. These are the
    # only cases where a second populated batch happens at all.
    def test_drains_every_batch_when_victims_exceed_batch_size(self, persons_conn, tmp_path):
        for n in range(5):
            _add_orphan_pair(persons_conn, _uuid(40 + n), f"did-40-{n}")
        assert _persons(persons_conn) == 10

        _run("delete-unreferenced", tmp_path, apply=True, batch_size=2)

        assert _persons(persons_conn) == 5
        assert _dup_groups(persons_conn) == 0
        assert _distinct_ids(persons_conn) == 5
        backed_up = [json.loads(line) for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        assert len([r for r in backed_up if r["_kind"] == "person"]) == 5, "every deleted row must be recoverable"

    def test_dry_run_checks_every_batch_not_just_the_first(self, persons_conn, tmp_path):
        # A dry run that returned after the first batch reported dry_run_batch_ok having
        # gated batch_size victims out of the whole staged set, which an operator reads as
        # clearance for the --apply run that follows.
        for n in range(3):
            _add_orphan_pair(persons_conn, _uuid(50 + n), f"did-50-{n}")

        with capture_logs() as logs:
            _run("delete-unreferenced", tmp_path, batch_size=1)

        assert _persons(persons_conn) == 6, "a dry run must delete nothing"
        assert list(tmp_path.glob("*.jsonl")) == []
        summary = next(entry for entry in logs if entry["event"] == "persons_dedup.dry_run_ok")
        assert summary["checked"] == 3
        assert summary["batches"] == 3


class TestPersonsDedupConcurrentWriters:
    # The in-transaction gates are the last thing standing between a wrong row and a silent
    # cascade into feature-flag overrides, and they are the only safety checks in this command
    # that a single-threaded test can never reach: staging excludes everything they catch, so
    # they fire only when a concurrent writer changes a staged victim mid-run. These two cases
    # drive that writer deterministically -- no threads, no sleeps.

    def test_a_victim_that_becomes_reachable_is_dropped_and_the_run_continues(
        self, persons_conn, tmp_path, monkeypatch
    ):
        # A returning user attaches a distinct ID to the orphan after it was staged. It is now
        # a live person, so deleting it would take its overrides with it.
        orphan, live = _add_orphan_pair_ids(persons_conn, _uuid(60), "did-60")

        def attach_a_mapping(other):
            _add_distinct_id(other, orphan, "did-60-returning")

        with _concurrent_write_before_delete(monkeypatch, attach_a_mapping) as fired:
            with capture_logs() as logs:
                _run("delete-unreferenced", tmp_path, apply=True)

        assert fired(), "the interfering write never ran; the test proves nothing"
        assert _persons(persons_conn) == 2, "the newly reachable row must not be deleted"
        assert any(entry["event"] == "persons_dedup.batch_raced" for entry in logs)
        assert any(entry["event"] == "persons_dedup.done" for entry in logs), "the run must finish, not abort"

    def test_a_group_that_loses_its_survivor_is_dropped_and_the_run_continues(
        self, persons_conn, tmp_path, monkeypatch
    ):
        # Something else deletes the survivor after staging. The staged victim is now the only
        # row holding that key, so it is no longer a duplicate and must not be deleted either.
        orphan, live = _add_orphan_pair_ids(persons_conn, _uuid(61), "did-61")

        def delete_the_survivor(other):
            with other.cursor() as cur:
                cur.execute("DELETE FROM posthog_persondistinctid WHERE team_id = %s AND person_id = %s", (TEAM, live))
                cur.execute("DELETE FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, live))

        with _concurrent_write_before_delete(monkeypatch, delete_the_survivor) as fired:
            with capture_logs() as logs:
                _run("delete-unreferenced", tmp_path, apply=True)

        assert fired(), "the interfering write never ran; the test proves nothing"
        remaining = _count(persons_conn, "SELECT id FROM posthog_person WHERE team_id = %s", (TEAM,))
        assert remaining == orphan, "the last row holding the key must survive"
        assert _persons(persons_conn) == 1
        assert any(entry["event"] == "persons_dedup.done" for entry in logs), "the run must finish, not abort"


class TestPersonsDedupRepair:
    # The shape every merge-required group in the production census shared: one row owns the
    # distinct ID, the other owns a flag override, neither owns both. This is also the only
    # place the two write modes disagree, so both arms are pinned here -- repair takes the
    # unreachable row and cascades its dead override away, delete-unreferenced refuses it
    # because the override is a reference. Swapping either staging predicate for the other
    # silently changes which rows a production run destroys.
    @pytest.mark.parametrize(
        "mode,expected_persons,expected_overrides,expected_dup_groups",
        [
            ("repair", 1, 0, 0),
            ("delete-unreferenced", 2, 1, 1),
        ],
    )
    def test_mode_divergence_on_the_production_shape(
        self, persons_conn, tmp_path, mode, expected_persons, expected_overrides, expected_dup_groups
    ):
        uuid = _uuid(20)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-20")
        stranded = _add_person(persons_conn, uuid)
        _add_flag_override(persons_conn, stranded, "flag-20")

        _run(mode, tmp_path, apply=True)

        assert _persons(persons_conn) == expected_persons
        assert _flag_overrides(persons_conn) == expected_overrides
        assert _dup_groups(persons_conn) == expected_dup_groups
        assert _distinct_ids(persons_conn) == 1

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

    def test_removes_and_backs_up_a_stranded_cohort_membership(self, persons_conn, tmp_path):
        # posthog_cohortpeople has no foreign key, so the cascade will not clear it and a
        # missed delete leaves a row pointing at a person that no longer exists.
        uuid = _uuid(25)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-25")
        stranded = _add_person(persons_conn, uuid)
        _add_cohort_member(persons_conn, stranded)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        assert _orphaned_cohort_rows(persons_conn) == 0
        records = [json.loads(line) for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        assert any(r["_kind"] == "cohortpeople" and r["person_id"] == stranded for r in records)

    def test_keeps_a_reachable_cohort_membership(self, persons_conn, tmp_path):
        uuid = _uuid(26)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-26")
        _add_cohort_member(persons_conn, live)
        _add_person(persons_conn, uuid)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        assert _cohort_rows(persons_conn) == 1

    def test_deletes_an_orphan_stranded_inside_a_merge_required_group(self, persons_conn, tmp_path):
        # Two live rows need a real merge, which this command refuses. The third row owns no
        # mapping and is dead on exactly the same terms as any other orphan -- its deadness has
        # nothing to do with what the other two are doing. Skipping it left known-dead rows
        # behind whose cohort memberships still counted toward the cohort size shown in the UI.
        uuid = _uuid(90)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-90a")
        _add_distinct_id(persons_conn, b, "did-90b")
        _add_person(persons_conn, uuid)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 2, "the orphan goes, both live rows stay"
        remaining = _count(
            persons_conn,
            "SELECT count(*) FROM posthog_person WHERE team_id = %s AND id = ANY(%s)",
            (TEAM, [a, b]),
        )
        assert remaining == 2
        assert _dup_groups(persons_conn) == 1, "the group still needs a merge and is still reported"

    def test_the_merge_required_group_is_still_reported_after_its_orphan_is_removed(self, persons_conn, tmp_path):
        uuid = _uuid(91)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-91a")
        _add_distinct_id(persons_conn, b, "did-91b")
        _add_person(persons_conn, uuid)

        _run("repair", tmp_path, apply=True)
        with capture_logs() as logs:
            _run("verify", tmp_path)

        result = next(entry for entry in logs if entry["event"] == "persons_dedup.verify")
        assert result["blocked_groups"] == 1
        assert result["resolvable_groups"] == 0, "removing the orphan must not make the group look resolvable"

    def test_all_orphan_group_keeps_the_identified_row(self, persons_conn, tmp_path):
        # A sizeable share of real duplicate groups have no member owning a distinct ID, so
        # the leading (n_did > 0) term in the survivor ranking cannot break the tie and the
        # rest of it decides alone. Nothing else exercises that branch, and getting it wrong
        # discards the richer row while keeping an empty one.
        uuid = _uuid(28)
        plain = _add_person(persons_conn, uuid)
        identified = _add_person(persons_conn, uuid, is_identified=True)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        survivor = _count(persons_conn, "SELECT id FROM posthog_person WHERE team_id = %s", (TEAM,))
        assert survivor == identified, "is_identified must outrank the plain row"
        assert plain != identified

    def test_never_deletes_a_tombstoned_row(self, persons_conn, tmp_path):
        # is_deleted is a revival marker, not a dead row: the write path reuses it so the
        # revived key outranks its own ClickHouse tombstone, which needs the version this
        # row holds. Deleting it would drop that version floor silently.
        uuid = _uuid(29)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-29")
        _add_person(persons_conn, uuid, is_deleted=True)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 2, "the tombstone must be left alone"
        assert _dup_groups(persons_conn) == 1

    def test_a_tombstone_never_outranks_a_live_row(self, persons_conn, tmp_path):
        # Neither row owns a distinct ID, so the leading term of the ranking ties and the
        # tombstone would win on is_identified and version -- making the live row the victim
        # and deleting the only row of the two that can still be revived into service.
        uuid = _uuid(33)
        _add_person(persons_conn, uuid, is_deleted=True, version=99, is_identified=True)
        live = _add_person(persons_conn, uuid)

        _run("repair", tmp_path, apply=True)

        survivors = _count(
            persons_conn, "SELECT count(*) FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, live)
        )
        assert survivors == 1, "the live row must outrank a higher-version identified tombstone"
        assert _persons(persons_conn) == 2, "and the tombstone itself is never staged"


class TestPersonsDedupSurvivorSelection:
    def test_a_row_reachable_only_through_a_tombstoned_mapping_loses_to_a_live_one(self, persons_conn, tmp_path):
        # The flag path requires pdi.is_deleted = false, so a tombstoned mapping does not make
        # a person reachable. Ranking on the raw mapping count would tie these two and let the
        # tiebreak keep the row the product cannot see.
        uuid = _uuid(80)
        tombstoned_owner = _add_person(persons_conn, uuid, is_identified=True, version=99)
        _add_distinct_id(persons_conn, tombstoned_owner, "did-80-dead", is_deleted=True)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-80-live")

        _run("classify", tmp_path)

        survivor = _count(
            persons_conn,
            "SELECT id FROM posthog_person p WHERE p.team_id = %s AND p.uuid = %s "
            "AND EXISTS (SELECT 1 FROM posthog_persondistinctid d "
            "WHERE d.person_id = p.id AND NOT d.is_deleted)",
            (TEAM, uuid),
        )
        assert survivor == live
        # Neither is deletable: both own a mapping, so the foreign key would block either way.
        _run("repair", tmp_path, apply=True)
        assert _persons(persons_conn) == 2

    def test_classify_writes_actionable_detail_for_groups_it_refuses(self, persons_conn, tmp_path):
        # A count of blocked groups cannot be acted on. Resolving one needs to know which rows
        # it holds, which are still reachable, and what hangs off them.
        uuid = _uuid(81)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-81a")
        _add_distinct_id(persons_conn, b, "did-81b")
        _add_flag_override(persons_conn, b, "flag-81")

        _run("classify", tmp_path)

        dumps = list(tmp_path.glob("blocked_team_*.jsonl"))
        assert dumps, "a refused group must leave a record behind"
        records = [json.loads(line) for line in dumps[0].read_text().splitlines()]
        assert len(records) == 1
        record = records[0]
        assert record["reason"] == "multiple_reachable_rows"
        assert record["reachable_owners"] == 2
        assert record["flag_overrides"] == 1
        assert sorted(record["reachable_ids"]) == sorted([a, b]), "both live rows must be named"

    def test_classify_writes_nothing_when_every_group_is_resolvable(self, persons_conn, tmp_path):
        _add_orphan_pair(persons_conn, _uuid(82), "did-82")

        _run("classify", tmp_path)

        assert list(tmp_path.glob("blocked_team_*.jsonl")) == []

    def test_a_tombstoned_member_is_named_as_the_blocking_reason(self, persons_conn, tmp_path):
        # A group whose only extra member is a tombstone is refused, and the reason has to name
        # the tombstone so the follow-up work is not sent at the wrong table.
        uuid = _uuid(83)
        survivor = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, survivor, "did-83")
        _add_person(persons_conn, uuid, is_deleted=True)

        _run("classify", tmp_path)

        records = [
            json.loads(line) for dump in tmp_path.glob("blocked_team_*.jsonl") for line in dump.read_text().splitlines()
        ]
        assert len(records) == 1
        assert records[0]["reason"] == "tombstoned_member"

    def test_two_distinct_id_owners_are_blocked_even_when_one_is_unreachable(self, persons_conn, tmp_path):
        # live_owners is what refuses the group; reachable_owners only says whether the product
        # can still resolve both. A reason keyed on reachable_owners alone called this 'other'.
        uuid = _uuid(84)
        survivor = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, survivor, "did-84")
        dead_owner = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, dead_owner, "did-84-dead", is_deleted=True)

        _run("classify", tmp_path)

        records = [
            json.loads(line) for dump in tmp_path.glob("blocked_team_*.jsonl") for line in dump.read_text().splitlines()
        ]
        assert len(records) == 1
        assert records[0]["reason"] == "multiple_distinct_id_owners"
        assert records[0]["live_owners"] == 2
        assert records[0]["reachable_owners"] == 1
        # Ordered by survivor rank, so the first id is the row the product can still resolve.
        # A transposed FILTER or ORDER BY in the aggregate would point the merge at the wrong row.
        assert records[0]["member_ids"] == [survivor, dead_owner]
        assert records[0]["reachable_ids"] == [survivor]
        # And the foreign key is why: the tombstoned mapping still references the row.
        _run("repair", tmp_path, apply=True)
        assert _persons(persons_conn) == 2


def _version(conn: psycopg.Connection, person_id: int) -> int:
    return _count(conn, "SELECT version FROM posthog_person WHERE id = %s", (person_id,))


class TestPersonsDedupSurvivorVersionFloor:
    # ClickHouse keys person rows on (team_id, uuid) and resolves them with argMax(..., version),
    # so both members of a duplicate group compete under one key. The survivor rule ranks
    # reachability above version, so the row we keep is routinely the lower-versioned one and its
    # later updates lose to the row we just deleted. These cover the raise that prevents that.

    @pytest.mark.parametrize(
        "victim_version,survivor_version,raised",
        [(1500, 3, True), (5, 5, True), (5, 88, False)],
        ids=["survivor below the ceiling", "survivor level with it", "survivor above it"],
    )
    def test_a_survivor_is_raised_only_when_a_victim_outranks_it(
        self, persons_conn, tmp_path, victim_version, survivor_version, raised
    ):
        # Level with the ceiling still has to be raised: equal versions tie in ClickHouse and
        # ReplacingMergeTree picks between them arbitrarily, so the survivor has to end up
        # strictly above. Tightening the guard to a strict "<" would leave that tie standing.
        # Above the ceiling is left alone rather than inflated for no gain.
        uuid = _uuid(200 if raised else 202)
        orphan = _add_person(persons_conn, uuid, version=victim_version)
        survivor = _add_person(persons_conn, uuid, version=survivor_version)
        _add_distinct_id(persons_conn, survivor, f"did-{200 if raised else 202}")

        _run("delete-unreferenced", tmp_path, apply=True, raise_survivor_version=True)

        assert _persons(persons_conn) == 1
        assert _count(persons_conn, "SELECT count(*) FROM posthog_person WHERE id = %s", (orphan,)) == 0
        expected = victim_version + persons_dedup_command.SURVIVOR_VERSION_MARGIN if raised else survivor_version
        assert _version(persons_conn, survivor) == expected

    def test_the_raise_clears_every_victim_in_a_group_not_just_one(self, persons_conn, tmp_path):
        # The ceiling is a max over the group's victims. Taking any single victim's version
        # would leave the survivor below a sibling that also wrote to the same ClickHouse key.
        uuid = _uuid(201)
        _add_person(persons_conn, uuid, version=40)
        _add_person(persons_conn, uuid, version=900)
        _add_person(persons_conn, uuid, version=7)
        survivor = _add_person(persons_conn, uuid, version=0)
        _add_distinct_id(persons_conn, survivor, "did-201")

        _run("delete-unreferenced", tmp_path, apply=True, raise_survivor_version=True)

        assert _persons(persons_conn) == 1
        assert _version(persons_conn, survivor) == 900 + persons_dedup_command.SURVIVOR_VERSION_MARGIN

    def test_a_survivor_already_above_its_victims_is_left_alone(self, persons_conn, tmp_path):
        # Raising unconditionally would inflate the counter of every survivor that never had
        # the problem, for no gain.
        uuid = _uuid(202)
        _add_person(persons_conn, uuid, version=5)
        survivor = _add_person(persons_conn, uuid, version=88)
        _add_distinct_id(persons_conn, survivor, "did-202")

        _run("delete-unreferenced", tmp_path, apply=True, raise_survivor_version=True)

        assert _version(persons_conn, survivor) == 88

    def test_a_merge_required_group_keeps_both_versions_untouched(self, persons_conn, tmp_path):
        # Two reachable rows plus an unreachable third. Repair may remove the third, but giving
        # both survivors the same version would make their ClickHouse rows tie rather than
        # resolve, so the group is left for the merge pass.
        uuid = _uuid(203)
        unreachable = _add_person(persons_conn, uuid, version=770)
        a = _add_person(persons_conn, uuid, version=2)
        b = _add_person(persons_conn, uuid, version=4)
        _add_distinct_id(persons_conn, a, "did-203a")
        _add_distinct_id(persons_conn, b, "did-203b")

        _run("repair", tmp_path, apply=True, raise_survivor_version=True)

        assert _count(persons_conn, "SELECT count(*) FROM posthog_person WHERE id = %s", (unreachable,)) == 0
        assert _version(persons_conn, a) == 2
        assert _version(persons_conn, b) == 4

    @pytest.mark.parametrize(
        "kwargs,raised",
        [({}, True), ({"raise_survivor_version": False}, False)],
        ids=["on by default", "--no-raise-survivor-version opts out"],
    )
    def test_the_raise_is_on_unless_a_run_opts_out(self, persons_conn, tmp_path, kwargs, raised):
        # A run that has to remember a flag to stay correct will eventually forget it, and the
        # cost of forgetting is a survivor whose ClickHouse row never updates again. The opt-out
        # still has to work, because it is the rollback if the wider lock ever contends.
        uuid = _uuid(204)
        _add_person(persons_conn, uuid, version=600)
        survivor = _add_person(persons_conn, uuid, version=1)
        _add_distinct_id(persons_conn, survivor, "did-204")

        _run("delete-unreferenced", tmp_path, apply=True, **kwargs)

        assert _persons(persons_conn) == 1
        expected = 600 + persons_dedup_command.SURVIVOR_VERSION_MARGIN if raised else 1
        assert _version(persons_conn, survivor) == expected

    def test_a_dry_run_counts_the_raises_without_making_them(self, persons_conn, tmp_path):
        # The flag has to be measurable before it writes to a row live ingestion also writes.
        uuid = _uuid(205)
        _add_person(persons_conn, uuid, version=500)
        survivor = _add_person(persons_conn, uuid, version=0)
        _add_distinct_id(persons_conn, survivor, "did-205")

        with capture_logs() as logs:
            _run("delete-unreferenced", tmp_path, raise_survivor_version=True)

        assert _persons(persons_conn) == 2, "a dry run deletes nothing"
        assert _version(persons_conn, survivor) == 0, "a dry run raises nothing"
        dry = [log for log in logs if log["event"] == "persons_dedup.dry_run_ok"]
        assert dry and dry[0]["survivors_to_raise"] == 1

    def test_the_raise_is_rolled_back_with_the_delete(self, persons_conn, tmp_path, monkeypatch):
        # The raise sits inside the delete transaction. If a later statement aborts it, a
        # survivor left carrying a raised version would claim a ClickHouse ceiling for rows
        # that were never removed.
        uuid = _uuid(206)
        _add_person(persons_conn, uuid, version=300)
        survivor = _add_person(persons_conn, uuid, version=0)
        _add_distinct_id(persons_conn, survivor, "did-206")

        def _explode(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(persons_dedup_command.Command, "_backup", _explode)
        with pytest.raises(RuntimeError):
            _run("delete-unreferenced", tmp_path, apply=True, raise_survivor_version=True)

        assert _persons(persons_conn) == 2
        assert _version(persons_conn, survivor) == 0

    @pytest.mark.parametrize(
        "raise_flag,expect_locked",
        [(True, True), (False, False)],
        ids=["flag on locks the survivor", "flag off leaves it alone"],
    )
    def test_the_survivor_lock_is_taken_up_front_and_only_when_asked(
        self, persons_conn, tmp_path, monkeypatch, raise_flag, expect_locked
    ):
        # The raise runs after the gates and an fsync'd backup. Taking the survivor's lock there
        # rather than up front reopens a deadlock: ingestion's updatePersonsBatch matches on
        # (team_id, uuid), so one statement needs both rows, and it can hold the survivor while
        # blocking on our victim. Probing during the backup proves the lock is already held.
        # The off case guards the other half -- the wider lock must not be paid by runs that did
        # not ask for it.
        uuid = _uuid(207 if raise_flag else 208)
        _add_person(persons_conn, uuid, version=400)
        survivor = _add_person(persons_conn, uuid, version=0)
        _add_distinct_id(persons_conn, survivor, f"did-{207 if raise_flag else 208}")

        observed: dict[str, Any] = {}
        real_backup = persons_dedup_command.Command._backup

        def backup_then_probe(self, conn, team, path):
            result = real_backup(self, conn, team, path)
            with persons_db_connection(writer=True, autocommit=True) as other:
                with other.cursor() as cur:
                    # Session-level, not SET LOCAL: this connection is in autocommit, where
                    # LOCAL is discarded with the implicit transaction and the probe would
                    # wait forever instead of failing fast.
                    cur.execute("SET lock_timeout = '250ms'")
                    try:
                        cur.execute("SELECT id FROM posthog_person WHERE id = %s FOR UPDATE", (survivor,))
                        observed["locked"] = False
                    except psycopg.errors.LockNotAvailable:
                        observed["locked"] = True
            return result

        monkeypatch.setattr(persons_dedup_command.Command, "_backup", backup_then_probe)
        _run("delete-unreferenced", tmp_path, apply=True, raise_survivor_version=raise_flag)

        assert observed["locked"] is expect_locked
        expected_version = 400 + persons_dedup_command.SURVIVOR_VERSION_MARGIN if raise_flag else 0
        assert _version(persons_conn, survivor) == expected_version

    def test_the_update_grant_is_only_required_when_the_flag_is_set(self):
        # The command runs today without UPDATE on posthog_person. Demanding it unconditionally
        # would abort every run whose role was granted exactly what the old modes needed.
        assert ("posthog_person", "UPDATE") not in persons_dedup_command.WRITE_PRIVILEGES
        assert ("posthog_person", "UPDATE") in persons_dedup_command.SURVIVOR_VERSION_PRIVILEGES
        assert set(persons_dedup_command.WRITE_PRIVILEGES) < set(persons_dedup_command.SURVIVOR_VERSION_PRIVILEGES)


class TestPersonsDedupVerify:
    def test_verify_fails_while_resolvable_duplicates_remain(self, persons_conn, tmp_path):
        # An orphan repair would have taken: work is genuinely outstanding.
        _add_orphan_pair(persons_conn, _uuid(30), "did-30")

        with pytest.raises(CommandError, match="resolvable duplicate group"):
            _run("verify", tmp_path)

    def test_verify_accepts_a_remainder_only_this_command_cannot_resolve(self, persons_conn, tmp_path):
        # Both rows own a distinct ID, so this needs a real person merge -- a separate
        # workstream. Raising here made verify useless as a release gate on exactly the
        # teams that have such groups, because its failure was indistinguishable from
        # "the dedup run did not finish".
        uuid = _uuid(31)
        a = _add_person(persons_conn, uuid)
        b = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, a, "did-31a")
        _add_distinct_id(persons_conn, b, "did-31b")

        with capture_logs() as logs:
            _run("verify", tmp_path)

        result = next(entry for entry in logs if entry["event"] == "persons_dedup.verify")
        assert result["duplicate_groups"] == 1
        assert result["blocked_groups"] == 1
        assert result["resolvable_groups"] == 0

    def test_verify_passes_once_clean(self, persons_conn, tmp_path):
        person = _add_person(persons_conn, _uuid(32))
        _add_distinct_id(persons_conn, person, "did-32")

        _run("verify", tmp_path)

    def test_batch_size_must_be_positive(self, persons_conn, tmp_path):
        # LIMIT 0 stages nothing, so the run would exit reporting success on a team that
        # still has duplicates -- indistinguishable from "already clean".
        uuid = _uuid(32)
        _add_person(persons_conn, uuid)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-32")

        with pytest.raises(CommandError, match="at least 1"):
            _run("delete-unreferenced", tmp_path, apply=True, batch_size=0)

        assert _persons(persons_conn) == 2

    def test_apply_is_rejected_for_read_only_modes(self, persons_conn, tmp_path):
        with pytest.raises(CommandError, match="meaningless"):
            _run("verify", tmp_path, apply=True)


class TestPersonsDedupTargetGuard:
    def test_refuses_to_run_when_the_persons_url_is_unset(self, monkeypatch, tmp_path):
        # Unset, posthog.persons_db builds a localhost URL from PG*. On a deployed pod those
        # point at the main cluster, so a silent fallback aims a destructive command at the
        # wrong database. It must refuse rather than connect.
        monkeypatch.delenv("PERSONS_DB_WRITER_URL", raising=False)
        monkeypatch.delenv("PERSONS_DB_READER_URL", raising=False)

        with pytest.raises(CommandError, match="PERSONS_DB_WRITER_URL is not set"):
            _run("repair", tmp_path, apply=True)

    def test_logs_the_host_and_dbname_it_is_about_to_modify(self, persons_conn, tmp_path):
        # The operator drives this by hand against production; host plus dbname is how they
        # confirm the toolbox is pointed at persons and not the main cluster.
        with capture_logs() as logs:
            _run("classify", tmp_path)

        target = [entry for entry in logs if entry["event"] == "persons_dedup.target"]
        assert len(target) == 1, "every run must say which database it targets"
        assert target[0]["dbname"]
        assert "password" not in str(target[0]), "the log line must not carry credentials"


class TestPersonsDedupLogVisibility:
    def test_info_records_survive_the_posthog_logger_clamp(self):
        # posthoganalytics calls logging.getLogger("posthog").setLevel(WARNING) at client init,
        # which happens during django.setup(). Without an explicit level on this module's logger
        # every INFO record is dropped, and three production runs of this command left no record
        # of what they did. structlog's capture_logs() replaces the processor chain, so it cannot
        # see this -- the assertion has to go through a real stdlib handler.
        parent = logging.getLogger("posthog")
        module_logger = logging.getLogger(persons_dedup_command.__name__)
        captured: list[logging.LogRecord] = []

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _Collector()
        original_level = parent.level
        original_disabled = module_logger.disabled
        original_global_disable = logging.root.manager.disable
        parent.setLevel(logging.WARNING)
        # Unrelated suites in the same worker reconfigure logging globally (dictConfig with
        # disable_existing_loggers, logging.disable), which suppresses every record regardless
        # of level. Clear both so the assertion isolates the one thing this test guards: the
        # module's own level beating the parent clamp.
        module_logger.disabled = False
        logging.disable(logging.NOTSET)
        module_logger.addHandler(handler)
        try:
            persons_dedup_command.logger.info("persons_dedup.log_visibility_probe", team_id=1)
        finally:
            module_logger.removeHandler(handler)
            module_logger.disabled = original_disabled
            logging.disable(original_global_disable)
            parent.setLevel(original_level)

        assert captured, "INFO records are dropped, so a production run would leave no log"
        assert captured[0].levelno == logging.INFO


class TestPersonsDedupPrivilegePreflight:
    def test_every_table_the_command_deletes_from_is_probed_for_delete(self):
        # The preflight exists so a missing grant aborts before any work. It is only worth
        # that if it covers every table written to -- a DELETE added without a matching
        # probe fails mid-transaction on the first team whose data reaches it.
        deleted_tables = set()
        for name, sql in vars(persons_dedup_command).items():
            if not name.startswith("DELETE_") or not isinstance(sql, str):
                continue
            match = re.search(r"DELETE\s+FROM\s+([a-z_]+)", sql, re.IGNORECASE)
            assert match, f"{name} does not look like a DELETE statement"
            deleted_tables.add(match.group(1))
        assert deleted_tables, "no DELETE_* constants found -- did they get renamed?"

        probed = {t for t, p in persons_dedup_command.WRITE_PRIVILEGES if p == "DELETE"}
        assert deleted_tables <= probed, f"deletes without a DELETE grant probe: {sorted(deleted_tables - probed)}"

    def test_read_modes_do_not_demand_delete_grants(self):
        # classify and verify delete nothing, so probing DELETE would block them on a
        # read-only role for grants they never exercise.
        assert {p for _, p in persons_dedup_command.READ_PRIVILEGES} == {"SELECT"}
        assert set(persons_dedup_command.READ_PRIVILEGES) <= set(persons_dedup_command.WRITE_PRIVILEGES)


class TestPersonsDedupConnectionRouting:
    # Both read modes default to the replica so a multi-minute census never holds a snapshot
    # on the primary. Silently moving either one back is the regression these guard against.
    # Locally the reader URL falls back to the writer, so the routed kwarg is the only
    # observable difference.
    @pytest.mark.parametrize(
        "mode,kwargs,expected_writer",
        [
            ("classify", {}, False),
            ("classify", {"reader": True}, False),
            ("classify", {"writer": True}, True),
            ("verify", {}, False),
            ("verify", {"writer": True}, True),
            ("verify", {"reader": True}, False),
            ("repair", {"apply": True}, True),
            ("delete-unreferenced", {"apply": True}, True),
        ],
    )
    def test_each_read_mode_honors_the_endpoint_the_operator_asks_for(
        self, persons_conn, tmp_path, monkeypatch, mode, kwargs, expected_writer
    ):
        requested = []
        real_connection = persons_db_connection

        def spy(*, writer: bool = True, autocommit: bool = False):
            requested.append(writer)
            return real_connection(writer=writer, autocommit=autocommit)

        monkeypatch.setattr(persons_dedup_command, "persons_db_connection", spy)

        _run(mode, tmp_path, **kwargs)

        assert requested == [expected_writer]

    @pytest.mark.parametrize("mode", ["classify", "verify"])
    def test_asking_for_both_endpoints_at_once_is_rejected(self, persons_conn, tmp_path, mode):
        # Neither flag wins by precedence; the operator is told to pick one rather than
        # finding out afterwards which endpoint actually served the answer.
        with pytest.raises(CommandError, match="mutually exclusive"):
            _run(mode, tmp_path, reader=True, writer=True)

    @pytest.mark.parametrize("mode", ["repair", "delete-unreferenced"])
    @pytest.mark.parametrize("flag", ["reader", "writer"])
    def test_endpoint_flags_are_rejected_on_the_write_modes(self, persons_conn, tmp_path, mode, flag):
        # A write mode has no endpoint choice. Accepting --reader would imply one exists,
        # and accepting --writer would imply the default was something else.
        with pytest.raises(CommandError, match="always uses the writer"):
            _run(mode, tmp_path, apply=True, **{flag: True})

    def test_a_replica_read_says_so_in_the_log(self, persons_conn, tmp_path, monkeypatch):
        # The operator needs to know which endpoint answered when two runs disagree. Local
        # Postgres is a primary, so pg_is_in_recovery() is stubbed to reach the branch.
        real_scalar = persons_dedup_command._scalar

        def in_recovery(conn, sql, params=None):
            if "pg_is_in_recovery" in sql:
                return 1
            return real_scalar(conn, sql, params)

        monkeypatch.setattr(persons_dedup_command, "_scalar", in_recovery)

        with capture_logs() as logs:
            _run("classify", tmp_path)

        replica_lines = [entry for entry in logs if entry["event"] == "persons_dedup.reading_from_replica"]
        assert replica_lines, "a replica read must be announced"
        assert replica_lines[0]["team_id"] == TEAM

    def test_a_primary_read_is_not_announced_as_a_replica_read(self, persons_conn, tmp_path):
        with capture_logs() as logs:
            _run("verify", tmp_path, writer=True)

        assert not [entry for entry in logs if entry["event"] == "persons_dedup.reading_from_replica"]


class TestPersonsDedupClassifyCounters:
    # classify's numbers decide how much work the rollout thinks is outstanding, and nothing
    # else asserts them. One fixture holding every group shape at once, because the counters
    # are computed in a single aggregate and a wrong FILTER shows up as one field disagreeing.
    def _seed_every_shape(self, conn) -> None:
        # No refs at all: both rows are orphans.
        _add_person(conn, _uuid(90))
        _add_person(conn, _uuid(90))

        # One reachable survivor plus one orphan. Resolvable.
        survivor = _add_person(conn, _uuid(91))
        _add_distinct_id(conn, survivor, "did-91")
        _add_person(conn, _uuid(91))

        # Two reachable rows: needs a real person merge.
        a = _add_person(conn, _uuid(92))
        b = _add_person(conn, _uuid(92))
        _add_distinct_id(conn, a, "did-92a")
        _add_distinct_id(conn, b, "did-92b")

        # Held by a tombstone, which repair will not touch.
        live = _add_person(conn, _uuid(93))
        _add_distinct_id(conn, live, "did-93")
        _add_person(conn, _uuid(93), is_deleted=True)

        # Referenced by everything except a distinct ID, so still resolvable.
        keeper = _add_person(conn, _uuid(94))
        _add_distinct_id(conn, keeper, "did-94")
        held = _add_person(conn, _uuid(94))
        _add_cohort_member(conn, held)
        _add_flag_override(conn, held, "flag-94")

    def test_classify_reports_every_counter_for_every_group_shape(self, persons_conn, tmp_path):
        self._seed_every_shape(persons_conn)

        with capture_logs() as logs:
            _run("classify", tmp_path)

        result = next(entry for entry in logs if entry["event"] == "persons_dedup.classify")
        assert result["dup_groups"] == 5
        assert result["all_orphaned"] == 1, "only uuid(90) has no referenced member"
        assert result["one_referenced"] == 2, "uuid(91) and uuid(93)"
        assert result["needs_merge"] == 2, "uuid(92) and uuid(94), which counts the held refs"
        assert result["groups_with_distinct_ids_on_multiple_rows"] == 1, "only uuid(92)"
        assert result["blocked_groups"] == 2, "uuid(92) needs a merge, uuid(93) holds a tombstone"
        assert result["resolvable_groups"] == 3
        assert result["tombstoned_members"] == 1
        assert result["distinct_ids"] == 5
        assert result["cohort_rows"] == 1
        assert result["flag_overrides"] == 1

    def test_a_long_step_is_bracketed_so_progress_is_visible(self, persons_conn, tmp_path):
        # A census emits nothing while it runs, so without these a slow scan and a hung one
        # look identical. The pid is what lets an operator check pg_stat_activity after an
        # interrupt.
        _add_orphan_pair(persons_conn, _uuid(95), "did-95")

        with capture_logs() as logs:
            _run("classify", tmp_path)

        started = next(e for e in logs if e["event"] == "persons_dedup.step_started" and e["step"] == "classify")
        finished = next(e for e in logs if e["event"] == "persons_dedup.step_finished" and e["step"] == "classify")
        assert isinstance(started["pid"], int)
        assert finished["elapsed_s"] >= 0


class TestPersonsDedupContention:
    def test_a_lock_timeout_retries_the_batch_and_reports_the_budget(self, persons_conn, tmp_path):
        # Ingestion holds locks on exactly these rows by design, so expiry is a normal event.
        # Letting LockNotAvailable escape ends the run and discards the staging census.
        victim, _survivor = _add_orphan_pair_ids(persons_conn, _uuid(96), "did-96")

        with persons_db_connection(writer=True, autocommit=True) as blocker:
            with blocker.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SELECT id FROM posthog_person WHERE team_id = %s AND id = %s FOR UPDATE", (TEAM, victim))
                try:
                    with pytest.raises(CommandError, match="lock contention") as raised:
                        _run("repair", tmp_path, apply=True, lock_timeout_ms=50, max_lock_retries=1)
                finally:
                    cur.execute("ROLLBACK")

        # Budget of 1 means it took the batch again before giving up, rather than dying on
        # first contact.
        assert "2 batch(es)" in str(raised.value)
        assert _persons(persons_conn) == 2, "nothing may be deleted when the lock was never held"


class TestPersonsDedupPlatformErrors:
    def test_an_unavailable_recovery_probe_does_not_end_the_run(self, persons_conn, tmp_path, monkeypatch):
        # The probe only labels a log line. Aurora withholds some introspection functions, and
        # letting one abort the run is how the previous failure shipped.
        real_scalar = persons_dedup_command._scalar

        def refuse_recovery_probe(conn, sql, params=None):
            if "pg_is_in_recovery" in sql:
                raise psycopg.errors.FeatureNotSupported("not supported on this platform")
            return real_scalar(conn, sql, params)

        monkeypatch.setattr(persons_dedup_command, "_scalar", refuse_recovery_probe)
        _add_orphan_pair(persons_conn, _uuid(97), "did-97")
        with capture_logs() as logs:
            _run("classify", tmp_path)

        assert [e for e in logs if e["event"] == "persons_dedup.recovery_probe_unavailable"]
        assert [e for e in logs if e["event"] == "persons_dedup.classify"], "the census still ran"

    def test_a_replica_conflict_is_retried_and_other_errors_are_not(self, persons_conn, monkeypatch):
        # Aurora cancels long reads on a reader to resolve replication conflicts, which
        # statement_timeout = 0 does not prevent. Losing a finished census to that is worse
        # than waiting. Anything else must surface immediately.
        monkeypatch.setattr(persons_dedup_command, "REPLICA_RETRY_BACKOFF_BASE_S", 0.0)
        calls = {"n": 0}

        def conflict_once():
            calls["n"] += 1
            if calls["n"] == 1:
                raise psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery")
            return "census"

        assert persons_dedup_command._retry_replica_conflict(persons_conn, "test", conflict_once) == "census"
        assert calls["n"] == 2

        def always_undefined():
            raise psycopg.errors.UndefinedTable("no such table")

        with pytest.raises(psycopg.errors.UndefinedTable):
            persons_dedup_command._retry_replica_conflict(persons_conn, "test", always_undefined)

    def test_a_persistent_replica_conflict_eventually_surfaces(self, persons_conn, monkeypatch):
        monkeypatch.setattr(persons_dedup_command, "REPLICA_RETRY_BACKOFF_BASE_S", 0.0)

        def always_conflict():
            raise psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery")

        with pytest.raises(psycopg.errors.SerializationFailure):
            persons_dedup_command._retry_replica_conflict(persons_conn, "test", always_conflict, attempts=2)


class TestPersonsDedupVerifyGate:
    def test_an_orphaned_mapping_does_not_fail_the_gate_and_is_not_scanned_for(self, persons_conn, tmp_path):
        # repair can neither create an orphaned mapping nor remove one, so gating on it blocked
        # the rollout on damage this command cannot fix. The scan costs several times the rest of
        # verify, so once it stopped gating there was no reason to keep paying for it.
        doomed = _add_person(persons_conn, _uuid(98))
        _add_distinct_id(persons_conn, doomed, "did-98")
        _orphan_a_distinct_id(persons_conn, doomed)

        with capture_logs() as logs:
            _run("verify", tmp_path)

        assert not [e for e in logs if e["event"] == "persons_dedup.step_started" and e["step"] == "verify_orphans"]
        assert next(e for e in logs if e["event"] == "persons_dedup.verify")["orphaned_distinct_ids"] is None

    def test_require_no_orphans_runs_the_scan_and_reports_the_count(self, persons_conn, tmp_path):
        doomed = _add_person(persons_conn, _uuid(97))
        _add_distinct_id(persons_conn, doomed, "did-97")
        _orphan_a_distinct_id(persons_conn, doomed)

        with capture_logs() as logs:
            with pytest.raises(CommandError, match="orphaned distinct id"):
                _run("verify", tmp_path, require_no_orphans=True)

        assert next(e for e in logs if e["event"] == "persons_dedup.verify")["orphaned_distinct_ids"] == 1

    def test_require_no_orphans_restores_the_stricter_gate(self, persons_conn, tmp_path):
        doomed = _add_person(persons_conn, _uuid(99))
        _add_distinct_id(persons_conn, doomed, "did-99")
        _orphan_a_distinct_id(persons_conn, doomed)

        with pytest.raises(CommandError, match="orphaned distinct id"):
            _run("verify", tmp_path, require_no_orphans=True)

    # The matrix runs against the decision itself, so the combinations do not each need a
    # seeded orphan.
    @pytest.mark.parametrize(
        "resolvable,orphans,require_no_orphans,expected",
        [
            (0, 0, False, []),
            (0, 3, False, []),
            (0, 3, True, ["3 orphaned distinct id(s)"]),
            (2, 0, False, ["2 resolvable duplicate group(s)"]),
            (2, 3, False, ["2 resolvable duplicate group(s)"]),
            (2, 3, True, ["2 resolvable duplicate group(s)", "3 orphaned distinct id(s)"]),
        ],
    )
    def test_orphans_gate_only_when_required(self, resolvable, orphans, require_no_orphans, expected):
        assert (
            persons_dedup_command._verify_failures(
                resolvable=resolvable, orphans=orphans, require_no_orphans=require_no_orphans
            )
            == expected
        )


class TestPersonsDedupReaderEndpoint:
    def test_reader_is_refused_when_no_reader_url_is_configured(self, persons_conn, tmp_path, monkeypatch):
        # The persons-DB URL silently falls back to the writer, so without this the flag whose
        # whole purpose is keeping a census off the primary would put it on the primary.
        monkeypatch.delenv("PERSONS_DB_READER_URL", raising=False)

        with pytest.raises(CommandError, match="PERSONS_DB_READER_URL"):
            _run("classify", tmp_path, reader=True)

    def test_reader_on_a_primary_session_warns_instead_of_aborting(self, persons_conn, tmp_path):
        # Single-node deployments point both URLs at one database, so --reader landing on the
        # primary is normal there. The read is harmless; only the silence would be a problem.
        with capture_logs() as logs:
            _run("classify", tmp_path, reader=True)

        assert [e for e in logs if e["event"] == "persons_dedup.reader_is_the_primary"]

    def test_the_default_read_falls_back_to_the_writer_and_says_so(self, persons_conn, tmp_path, monkeypatch):
        monkeypatch.delenv("PERSONS_DB_READER_URL", raising=False)

        with capture_logs() as logs:
            _run("classify", tmp_path)

        assert [e for e in logs if e["event"] == "persons_dedup.no_reader_configured"]


def _spread_uuid(index: int, total: int) -> str:
    # _uuid() returns tiny integers, which all land in the first uuid slice, so a fixture built
    # from it would never exercise slicing. These sit in widely separated regions of the space.
    return str(uuid_mod.UUID(int=index * ((1 << 128) // total) + 7))


class TestPersonsDedupCensusSlicing:
    # Slicing the uuid space must not change any answer. 1 is the unsliced fallback; the larger
    # counts put slice boundaries between the fixture's groups.
    SLICES = [1, 2, 3, 64]
    SHAPES = 5

    def _seed(self, conn) -> None:
        for shape in range(self.SHAPES):
            uuid = _spread_uuid(shape, self.SHAPES)
            a = _add_person(conn, uuid)
            b = _add_person(conn, uuid, is_deleted=(shape == 3))
            if shape >= 1:
                _add_distinct_id(conn, a, f"spread-{shape}a")
            if shape == 2:
                _add_distinct_id(conn, b, f"spread-{shape}b")
            if shape == 4:
                _add_cohort_member(conn, b)
                _add_flag_override(conn, b, f"spread-flag-{shape}")

    @pytest.mark.parametrize("slices", SLICES)
    def test_classify_reports_the_same_totals_at_any_slice_count(self, persons_conn, tmp_path, slices):
        self._seed(persons_conn)

        with capture_logs() as logs:
            _run("classify", tmp_path, census_slices=slices)

        result = next(e for e in logs if e["event"] == "persons_dedup.classify")
        assert {key: result[key] for key in persons_dedup_command.CLASSIFY_COLUMNS} == {
            "dup_groups": 5,
            "all_orphaned": 1,
            "one_referenced": 2,
            "needs_merge": 2,
            "groups_with_distinct_ids_on_multiple_rows": 1,
            "blocked_groups": 2,
            "tombstoned_members": 1,
            "distinct_ids": 5,
            "cohort_rows": 1,
            "flag_overrides": 1,
        }
        assert result["resolvable_groups"] == 3

    @pytest.mark.parametrize("slices", SLICES)
    def test_blocked_detail_is_the_same_at_any_slice_count(self, persons_conn, tmp_path, slices):
        # Written per slice, so a boundary between two blocked groups must not drop or duplicate
        # either one.
        self._seed(persons_conn)

        _run("classify", tmp_path, census_slices=slices)

        records = [
            json.loads(line) for dump in tmp_path.glob("blocked_team_*.jsonl") for line in dump.read_text().splitlines()
        ]
        assert sorted(r["reason"] for r in records) == ["multiple_reachable_rows", "tombstoned_member"]
        assert len({r["uuid"] for r in records}) == 2, "one record per blocked group, no duplicates"

    @pytest.mark.parametrize("slices", SLICES)
    def test_verify_counts_the_same_at_any_slice_count(self, persons_conn, tmp_path, slices):
        self._seed(persons_conn)

        with capture_logs() as logs:
            with pytest.raises(CommandError):
                _run("verify", tmp_path, census_slices=slices)

        result = next(e for e in logs if e["event"] == "persons_dedup.verify")
        assert result["duplicate_groups"] == 5
        assert result["blocked_groups"] == 2
        assert result["resolvable_groups"] == 3

    @pytest.mark.parametrize("slices", SLICES)
    def test_repair_stages_and_deletes_the_same_victims_at_any_slice_count(self, persons_conn, tmp_path, slices):
        # Staging runs one transaction per slice, so a boundary must not leave a victim unstaged.
        for shape in range(self.SHAPES):
            _add_orphan_pair(persons_conn, _spread_uuid(shape, self.SHAPES), f"spread-repair-{shape}")
        assert _persons(persons_conn) == 10

        with capture_logs() as logs:
            _run("repair", tmp_path, apply=True, census_slices=slices)

        assert _persons(persons_conn) == 5, "every orphan is staged and deleted whatever the slicing"
        assert _dup_groups(persons_conn) == 0
        assert next(e for e in logs if e["event"] == "persons_dedup.staged")["victims"] == 5


class TestPersonsDedupResume:
    def test_a_run_can_resume_from_its_checkpoint_without_restaging(self, persons_conn, tmp_path, monkeypatch):
        # An interrupted run used to lose the whole staging census. The checkpoint holds the
        # victims still to delete, so a rerun picks up where it stopped.
        for shape in range(4):
            _add_orphan_pair(persons_conn, _uuid(300 + shape), f"did-300-{shape}")
        assert _persons(persons_conn) == 8

        # Stop the run after its first batch, the way a lost connection or a Ctrl-C would.
        real_prune = persons_dedup_command.Command._prune_batch

        class Stop(Exception):
            pass

        calls = {"n": 0}
        real_write = persons_dedup_command.Command._write_checkpoint

        def stop_after_second_checkpoint(self, conn, path, *, team, staged):
            real_write(self, conn, path, team=team, staged=staged)
            calls["n"] += 1
            if calls["n"] == 2:
                raise Stop()

        monkeypatch.setattr(persons_dedup_command.Command, "_write_checkpoint", stop_after_second_checkpoint)
        with pytest.raises(Stop):
            _run("repair", tmp_path, apply=True, batch_size=1, checkpoint_every=1)

        monkeypatch.setattr(persons_dedup_command.Command, "_prune_batch", real_prune)
        monkeypatch.undo()
        deleted_first = 8 - _persons(persons_conn)
        assert deleted_first == 1, "one batch of one victim landed before the stop"

        checkpoint = tmp_path / f"remaining_team_{TEAM}_repair.csv"
        assert checkpoint.exists()
        assert len(checkpoint.read_text().splitlines()) == 3, "the three victims still to delete"

        with capture_logs() as logs:
            _run("repair", tmp_path, apply=True, resume_from=str(checkpoint))

        assert next(e for e in logs if e["event"] == "persons_dedup.resumed")["victims"] == 3
        assert not [e for e in logs if e["event"] == "persons_dedup.step_started" and e["step"] == "stage"], (
            "resuming must not re-run the census"
        )
        assert _persons(persons_conn) == 4
        assert _dup_groups(persons_conn) == 0

    def test_a_stale_checkpoint_entry_is_pruned_rather_than_deleted(self, persons_conn, tmp_path):
        # Staging is not authoritative; the gates are. A victim that became reachable after the
        # checkpoint was written must be dropped, not deleted.
        victim, _survivor = _add_orphan_pair_ids(persons_conn, _uuid(310), "did-310")
        checkpoint = tmp_path / "stale.csv"
        checkpoint.write_text(f"{TEAM},{victim},{_uuid(310)}\n")

        _add_distinct_id(persons_conn, victim, "did-310-rescued")

        _run("repair", tmp_path, apply=True, resume_from=str(checkpoint))

        assert _persons(persons_conn) == 2, "the rescued row must survive"

    def test_a_checkpoint_for_another_team_is_refused(self, persons_conn, tmp_path):
        # The gates only ever look at the staged set, so they cannot catch this.
        checkpoint = tmp_path / "wrong-team.csv"
        checkpoint.write_text(f"{TEAM + 1},999999,{_uuid(311)}\n")

        with pytest.raises(CommandError, match="different team"):
            _run("repair", tmp_path, apply=True, resume_from=str(checkpoint))

    def test_resume_from_is_rejected_for_read_modes(self, persons_conn, tmp_path):
        with pytest.raises(CommandError, match="meaningless"):
            _run("classify", tmp_path, resume_from="/nonexistent")

    def test_a_checkpoint_naming_already_deleted_victims_is_reconciled_not_pruned(self, persons_conn, tmp_path):
        # Every prune counts against a budget meant for staging and the gate disagreeing, so a
        # checkpoint written a few batches before the interruption must not spend it on rows whose
        # absence is expected.
        victim, _survivor = _add_orphan_pair_ids(persons_conn, _uuid(320), "did-320")
        live_victim, _live_survivor = _add_orphan_pair_ids(persons_conn, _uuid(321), "did-321")
        with persons_conn.cursor() as cur:
            cur.execute("DELETE FROM posthog_person WHERE team_id = %s AND id = %s", (TEAM, victim))

        checkpoint = tmp_path / "with-deleted.csv"
        checkpoint.write_text(f"{TEAM},{victim},{_uuid(320)}\n{TEAM},{live_victim},{_uuid(321)}\n")

        with capture_logs() as logs:
            _run("repair", tmp_path, apply=True, resume_from=str(checkpoint))

        assert next(e for e in logs if e["event"] == "persons_dedup.checkpoint_reconciled")["already_deleted"] == 1
        assert next(e for e in logs if e["event"] == "persons_dedup.staged")["victims"] == 1
        assert not [e for e in logs if e["event"] == "persons_dedup.batch_raced"], "no prune budget spent"
        assert _persons(persons_conn) == 2
