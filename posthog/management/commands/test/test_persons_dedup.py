from __future__ import annotations

import re
import json
import uuid as uuid_mod
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
        cur.execute("DELETE FROM posthog_person_reconciliation_backup WHERE team_id = %s", (TEAM,))
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
# only a concurrent writer can make a staged victim undeletable. Keyed on the gate SQL rather
# than a call count so it stays put if another pre-flight check is added.
@contextmanager
def _concurrent_write_before_delete(monkeypatch, action):
    real_scalar = persons_dedup_command._scalar
    state = {"fired": False}

    def scalar_then_interfere(conn, sql, params=None):
        result = real_scalar(conn, sql, params)
        if not state["fired"] and "victims >= members" in sql:
            state["fired"] = True
            with persons_db_connection(writer=True, autocommit=True) as other:
                action(other)
        return result

    monkeypatch.setattr(persons_dedup_command, "_scalar", scalar_then_interfere)
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


def _add_recon_backup_row(conn: psycopg.Connection, person_id: int, uuid: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_person_reconciliation_backup "
            "(job_id, team_id, person_id, uuid, properties, is_identified, created_at, pending_operations) "
            "VALUES ('test-job', %s, %s, %s, '{}'::jsonb, false, now(), '{}'::jsonb)",
            (TEAM, person_id, uuid),
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

    def test_deletes_an_orphan_the_reconciliation_backup_references_and_takes_the_backup_row(
        self, persons_conn, tmp_path
    ):
        # A reconciliation backup row does not make a person live. Its restore path reads the
        # person by id and treats a missing row as a skip, so refusing this delete only left a
        # dead row behind, plus a backup row that would warn on every future restore and keep
        # the deleted person's properties. Both go together now.
        uuid = _uuid(27)
        live = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, live, "did-27")
        held = _add_person(persons_conn, uuid)
        _add_recon_backup_row(persons_conn, held, uuid)

        _run("repair", tmp_path, apply=True)

        assert _persons(persons_conn) == 1
        assert _dup_groups(persons_conn) == 0
        assert (
            _count(
                persons_conn,
                "SELECT count(*) FROM posthog_person_reconciliation_backup WHERE team_id = %s",
                (TEAM,),
            )
            == 0
        ), "the backup row must not outlive the person it describes"
        records = [json.loads(line) for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
        assert any(r["_kind"] == "reconciliation_backup" and r["person_id"] == held for r in records), (
            "the backup row must be recoverable from the undo file"
        )

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

    def test_a_reconciliation_backup_row_does_not_claim_the_blocking_reason(self, persons_conn, tmp_path):
        # The backup stopped refusing deletes, so it must not be named as the cause either.
        # This group is held by its tombstone; attributing it to the backup would send the
        # follow-up work at the wrong table.
        uuid = _uuid(83)
        survivor = _add_person(persons_conn, uuid)
        _add_distinct_id(persons_conn, survivor, "did-83")
        tombstoned = _add_person(persons_conn, uuid, is_deleted=True)
        _add_recon_backup_row(persons_conn, tombstoned, uuid)

        _run("classify", tmp_path)

        records = [
            json.loads(line) for dump in tmp_path.glob("blocked_team_*.jsonl") for line in dump.read_text().splitlines()
        ]
        assert len(records) == 1
        assert records[0]["reason"] == "tombstoned_member"
        assert records[0]["recon_held"] == 1, "still reported, just not as the reason"

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
        # And the foreign key is why: the tombstoned mapping still references the row.
        _run("repair", tmp_path, apply=True)
        assert _persons(persons_conn) == 2


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


class TestPersonsDedupPrivilegePreflight:
    def test_every_table_the_command_deletes_from_is_probed_for_delete(self):
        # The preflight exists so a missing grant aborts before any work. It is only worth
        # that if it covers every table written to -- a DELETE added without a matching
        # probe fails mid-transaction on the first team whose data reaches it, which is
        # exactly how the reconciliation-backup delete shipped.
        deleted_tables = set()
        for name, sql in vars(persons_dedup_command).items():
            if not name.startswith("DELETE_") or not isinstance(sql, str):
                continue
            match = re.search(r"DELETE\s+FROM\s+([a-z_]+)", sql, re.IGNORECASE)
            assert match, f"{name} does not look like a DELETE statement"
            deleted_tables.add(match.group(1))
        assert deleted_tables, "no DELETE_* constants found -- did they get renamed?"

        probed = {t for t, p in persons_dedup_command.REQUIRED_PRIVILEGES if p == "DELETE"}
        assert deleted_tables <= probed, f"deletes without a DELETE grant probe: {sorted(deleted_tables - probed)}"


class TestPersonsDedupConnectionRouting:
    # The reads can scan for minutes on large teams; silently moving them back to the
    # primary is the regression these guard against. Locally the reader URL falls back
    # to the writer, so the routed kwarg is the only observable difference.
    @pytest.mark.parametrize(
        "mode,kwargs,expected_writer",
        [
            ("classify", {}, False),
            ("verify", {}, False),
            ("classify", {"writer": True}, True),
            ("repair", {"apply": True}, True),
        ],
    )
    def test_read_modes_use_the_reader_unless_writer_is_forced(
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

    def test_writer_flag_is_rejected_for_write_modes(self, persons_conn, tmp_path):
        with pytest.raises(CommandError, match="always uses the writer"):
            _run("repair", tmp_path, writer=True)
