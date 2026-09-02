import itertools
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

import pytest
from unittest.mock import patch

import dagster
import psycopg2
from clickhouse_driver import Client
from psycopg2 import OperationalError

from posthog.clickhouse.cleanup_snapshots import (
    CLEANUP_DELETED_PERSONS_TABLE,
    CLEANUP_ORPHANED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_PERSONS_TABLE,
    CLEANUP_SNAPSHOT_TABLES,
)
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags import clickhouse_cleanup
from posthog.dags.clickhouse_cleanup import (
    PG_CLEANUP_QUEUE_TABLE,
    MutationProgress,
    MutationStalled,
    MutationStatus,
    OrphanedDistinctIdsTable,
    clickhouse_deletion_sweep_job,
)
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.persons_db import persons_db_url

TEAM_ID = 4242
COHORT_ID = 77

# dry_run defaults to true, so a real sweep opts in. Declared on the first op alone, which is
# what stops a launch from setting it on one op and missing another.
RUN_FOR_REAL = {"ops": {"clear_removed_cohort_data": {"config": {"dry_run": False}}}}


@pytest.fixture
def persons_database() -> Iterator[psycopg2.extensions.connection]:
    conn = psycopg2.connect(persons_db_url(writer=True))
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"TRUNCATE {PG_CLEANUP_QUEUE_TABLE}")
        conn.commit()
        yield conn
    finally:
        conn.close()


def run_job(cluster: ClickhouseCluster, persons_database, run_config=RUN_FOR_REAL, raise_on_error=True, instance=None):
    return clickhouse_deletion_sweep_job.execute_in_process(
        run_config=run_config,
        resources={"cluster": cluster, "persons_database_url": persons_db_url(writer=True)},
        raise_on_error=raise_on_error,
        instance=instance,
    )


def visible_persons(client: Client) -> int:
    # SELECT hides lightweight-deleted rows, so this counts what survived the sweep.
    [[count]] = client.execute("SELECT count() FROM person WHERE team_id = %(team_id)s", {"team_id": TEAM_ID})
    return count


def current_persons(client: Client) -> int:
    [[count]] = client.execute("SELECT count() FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": TEAM_ID})
    return count


def rows_for(person_uuid: str):
    # Raw row count, so it sees every surviving version rather than the collapsed one.
    def query(client: Client) -> int:
        [[count]] = client.execute(
            "SELECT count() FROM person WHERE team_id = %(team_id)s AND id = %(id)s",
            {"team_id": TEAM_ID, "id": person_uuid},
        )
        return count

    return query


def surviving_distinct_ids(client: Client) -> set[str]:
    rows = client.execute(
        "SELECT DISTINCT distinct_id FROM person_distinct_id2 WHERE team_id = %(team_id)s", {"team_id": TEAM_ID}
    )
    return {row[0] for row in rows}


def current_owner(distinct_id: str):
    def query(client: Client) -> UUID | None:
        rows = client.execute(
            """
            SELECT argMax(person_id, version)
            FROM person_distinct_id2
            WHERE team_id = %(team_id)s AND distinct_id = %(distinct_id)s
            GROUP BY distinct_id
            """,
            {"team_id": TEAM_ID, "distinct_id": distinct_id},
        )
        return rows[0][0] if rows else None

    return query


def cohort_rows(client: Client) -> int:
    [[count]] = client.execute("SELECT count() FROM cohortpeople WHERE team_id = %(team_id)s", {"team_id": TEAM_ID})
    return count


def dictionaries_for_run(run_id: str):
    """Count only this run's dictionaries.

    Scoped to the run rather than the table prefixes, so the assertion cannot be thrown off by
    leftovers another test or an earlier session left in the shared dev database.
    """
    suffix = f"%{run_id.replace('-', '_')}%"

    def query(client: Client) -> int:
        [[dictionaries]] = client.execute(
            "SELECT count() FROM system.dictionaries WHERE name LIKE %(suffix)s", {"suffix": suffix}
        )
        return dictionaries

    return query


def snapshot_rows_for_run(run_id: str):
    """Count this run's rows across every snapshot table.

    The tables are created by migration and outlive every run, so what a run has to clean up is
    its rows rather than the tables. Anchored to the constants, not to literals that can drift out
    of step with a rename.
    """
    scoped = run_id.replace("-", "_")

    def query(client: Client) -> int:
        return sum(
            client.execute(
                f"SELECT count() FROM {table} WHERE run_id = %(run_id)s",
                {"run_id": scoped},
            )[0][0]
            for table in CLEANUP_SNAPSHOT_TABLES
        )

    return query


DECOY_RUN_ID = "decoy_run"


def seed_decoy_run(cluster: ClickhouseCluster, spared_person: str, spared_distinct_id: str, doomed_person: str) -> None:
    """Fill every snapshot table with a second run's rows, chosen to break this run if it reads them.

    The worklists name a live person and a live mapping, so an unscoped read would delete them. The
    exclusion tables name the person this run is deleting, so an unscoped read would spare it.
    """

    def seed(client: Client) -> None:
        client.execute(
            f"INSERT INTO {CLEANUP_DELETED_PERSONS_TABLE} (run_id, team_id, person_id, max_version) VALUES",
            [(DECOY_RUN_ID, TEAM_ID, spared_person, 0)],
        )
        client.execute(
            f"INSERT INTO {CLEANUP_ORPHANED_DISTINCT_IDS_TABLE}"
            " (run_id, team_id, distinct_id, person_id, own_tombstone, max_version) VALUES",
            [(DECOY_RUN_ID, TEAM_ID, spared_distinct_id, spared_person, 1, 0)],
        )
        client.execute(
            f"INSERT INTO {CLEANUP_REVIVED_PERSONS_TABLE} (run_id, team_id, person_id) VALUES",
            [(DECOY_RUN_ID, TEAM_ID, doomed_person)],
        )
        client.execute(
            f"INSERT INTO {CLEANUP_REVIVED_DISTINCT_IDS_TABLE} (run_id, team_id, distinct_id) VALUES",
            [(DECOY_RUN_ID, TEAM_ID, "gone")],
        )

    cluster.any_host(seed).result()
    cluster.map_all_hosts(
        lambda client: [client.execute(f"SYSTEM SYNC REPLICA {table} STRICT") for table in CLEANUP_SNAPSHOT_TABLES]
    ).result()


def queued_rows(conn) -> list[tuple]:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT team_id, person_uuid, deleted_at, cleaned_at FROM {PG_CLEANUP_QUEUE_TABLE} ORDER BY 2")
        return cursor.fetchall()


def seed_cohort_rows(cluster: ClickhouseCluster, count: int) -> None:
    rows = [(TEAM_ID, UUID(int=i), COHORT_ID, 1) for i in range(count)]
    cluster.any_host(
        lambda client: client.execute("INSERT INTO cohortpeople (team_id, person_id, cohort_id, sign) VALUES", rows)
    ).result()


@pytest.mark.django_db
def test_deletes_soft_deleted_persons_and_preserves_the_rest(cluster: ClickhouseCluster, persons_database):
    # Deleted at a later version: every version has to go, which is why the delete keys on the
    # person rather than on is_deleted.
    deleted_later = create_person(team_id=TEAM_ID, version=0, is_deleted=False)
    create_person(uuid=deleted_later, team_id=TEAM_ID, version=1, is_deleted=True)
    # Deleted at its only version.
    deleted_once = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    # Never deleted.
    live = create_person(team_id=TEAM_ID, version=0)
    # Deleted, then revived by a higher version: currently live, so it has to survive. Dropping the
    # argMax gate for a plain is_deleted check would delete this person.
    revived = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person(uuid=revived, team_id=TEAM_ID, version=1, is_deleted=False)

    run_job(cluster, persons_database)

    # The live version of deleted_later would survive a delete keyed on is_deleted rather than on
    # the person, so this asserts on the raw count rather than the collapsed one.
    assert cluster.any_host(rows_for(deleted_later)).result() == 0
    assert cluster.any_host(rows_for(deleted_once)).result() == 0
    assert cluster.any_host(rows_for(live)).result() == 1
    assert cluster.any_host(rows_for(revived)).result() > 0
    # Survivor counts go through FINAL: a background merge may collapse the revived person's two
    # versions at any point, so its raw count is not stable.
    assert cluster.any_host(current_persons).result() == 2


@pytest.mark.django_db
def test_removes_distinct_ids_of_deleted_persons_and_keeps_live_ones(cluster: ClickhouseCluster, persons_database):
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    live = create_person(team_id=TEAM_ID, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="gone", person_id=deleted, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="kept", person_id=live, version=0)

    run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == {"kept"}


@pytest.mark.django_db
def test_removes_a_distinct_id_that_tombstoned_itself(cluster: ClickhouseCluster, persons_database):
    # The mapping is tombstoned while its person stays live, which is the leak the person-driven
    # arm alone would miss.
    live = create_person(team_id=TEAM_ID, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="detached", person_id=live, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="detached", person_id=live, version=100, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="kept", person_id=live, version=0)

    run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == {"kept"}


@pytest.mark.django_db
def test_keeps_a_distinct_id_repointed_to_a_live_person(cluster: ClickhouseCluster, persons_database):
    # Newest version points at a live person, so the mapping is in use and has to stay whole.
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    live = create_person(team_id=TEAM_ID, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="moved", person_id=deleted, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="moved", person_id=live, version=1)

    run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == {"moved"}
    assert cluster.any_host(current_owner("moved")).result() == UUID(live)


@pytest.mark.django_db
def test_removes_every_version_of_a_distinct_id_repointed_to_a_deleted_person(
    cluster: ClickhouseCluster, persons_database
):
    # Newest version points at a deleted person. Deleting only the rows whose person_id matches
    # would strip that row and hand the mapping back to the live person underneath it.
    live = create_person(team_id=TEAM_ID, version=0)
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="moved", person_id=live, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="moved", person_id=deleted, version=1)

    run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == set()
    assert cluster.any_host(current_owner("moved")).result() is None


@pytest.mark.django_db
def test_queues_the_deleted_persons_for_postgres(cluster: ClickhouseCluster, persons_database):
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person(team_id=TEAM_ID, version=0)

    run_job(cluster, persons_database)

    rows = queued_rows(persons_database)
    assert len(rows) == 1
    team_id, person_uuid, deleted_at, cleaned_at = rows[0]
    assert (team_id, str(person_uuid)) == (TEAM_ID, deleted)
    assert deleted_at is not None
    assert cleaned_at is None

    # A second run must not raise on the primary key: it re-queues persons the drain has not
    # reached yet.
    run_job(cluster, persons_database)
    assert len(queued_rows(persons_database)) == 1


@pytest.mark.django_db
def test_queues_every_person_across_page_boundaries(cluster: ClickhouseCluster, persons_database, monkeypatch):
    # The handoff pages its ClickHouse read by keyset and commits per page; an off-by-one at a
    # page edge, or stopping after a full page that happened to be the last, silently drops
    # persons from the queue and leaks their Postgres rows forever.
    monkeypatch.setattr(clickhouse_cleanup, "PERSIST_PAGE_SIZE", 2)
    expected = sorted(create_person(team_id=TEAM_ID, version=0, is_deleted=True) for _ in range(5))

    run_job(cluster, persons_database)

    assert sorted(str(row[1]) for row in queued_rows(persons_database)) == expected


@pytest.mark.django_db
def test_requeues_a_person_the_drain_already_cleaned(cluster: ClickhouseCluster, persons_database):
    # A person can be deleted, drained, then re-created and deleted again under the same uuid. The
    # drain only reads rows where cleaned_at is null, so leaving the cleaned row untouched would
    # drop the second deletion and leak that person's Postgres rows for good.
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    run_job(cluster, persons_database)

    # Stand in for the drain having processed it.
    with persons_database.cursor() as cursor:
        cursor.execute(f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET cleaned_at = now()")
    persons_database.commit()
    assert queued_rows(persons_database)[0][3] is not None

    # The same person is deleted again at a higher version, so a later run snapshots it afresh.
    create_person(uuid=deleted, team_id=TEAM_ID, version=10, is_deleted=True)
    run_job(cluster, persons_database)

    rows = queued_rows(persons_database)
    assert len(rows) == 1, "the row is keyed on (team_id, person_uuid), so this stays a single row"
    assert rows[0][3] is None, "cleaned_at must be cleared so the drain picks the person up again"


def _foreign_run_dictionary(cluster: ClickhouseCluster, run_id: str) -> clickhouse_cleanup.SnapshotDictionary:
    # A stranded dictionary the way a dead run leaves one: created on every host, source table
    # rows irrelevant (the janitor drops by name, never by content).
    scoped = run_id.replace("-", "_")
    dictionary = clickhouse_cleanup.SnapshotDictionary(
        source=clickhouse_cleanup.DeletedPersonsTable(run_id=scoped),
        excluded=clickhouse_cleanup.RevivedPersonsTable(run_id=scoped),
    )
    cluster.map_all_hosts(partial(dictionary.create, shards=1, max_execution_time=0, max_memory_usage=0)).result()
    return dictionary


@pytest.mark.django_db
def test_the_janitor_reaps_a_terminal_runs_dictionaries(cluster: ClickhouseCluster, persons_database):
    # Cancellation and pre-step failures fire no hook, so their dictionaries survive until the
    # next run reaps them. Dropping the janitor call, or breaking its name parse, leaks tens of
    # GiB per host per dead run with no path back but manual DDL.
    instance = dagster.DagsterInstance.ephemeral()
    dead = instance.create_run_for_job(job_def=clickhouse_deletion_sweep_job, status=dagster.DagsterRunStatus.FAILURE)
    _foreign_run_dictionary(cluster, dead.run_id)
    assert cluster.any_host(dictionaries_for_run(dead.run_id)).result() == 1

    result = run_job(cluster, persons_database, instance=instance)

    assert result.success
    assert cluster.any_host(dictionaries_for_run(dead.run_id)).result() == 0


@pytest.mark.django_db
def test_the_janitor_leaves_an_active_runs_dictionaries_alone(cluster: ClickhouseCluster, persons_database):
    # An active run's dictionaries are in use; reaping them would let two runs eat each other's
    # worklists, which is the isolation the whole run-id scoping exists to protect.
    instance = dagster.DagsterInstance.ephemeral()
    active = instance.create_run_for_job(job_def=clickhouse_deletion_sweep_job, status=dagster.DagsterRunStatus.STARTED)
    dictionary = _foreign_run_dictionary(cluster, active.run_id)
    try:
        result = run_job(cluster, persons_database, instance=instance)
        assert result.success
        assert cluster.any_host(dictionaries_for_run(active.run_id)).result() == 1
    finally:
        cluster.map_all_hosts(dictionary.drop).result()


@pytest.mark.django_db
def test_the_janitor_leaves_unknown_dictionaries_alone(cluster: ClickhouseCluster, persons_database):
    # A run id this instance does not know cannot be proven dead, so it must survive with a
    # warning rather than be guessed at.
    stranger = "99999999-9999-4999-8999-999999999999"
    dictionary = _foreign_run_dictionary(cluster, stranger)
    try:
        result = run_job(cluster, persons_database, instance=dagster.DagsterInstance.ephemeral())
        assert result.success
        assert cluster.any_host(dictionaries_for_run(stranger)).result() == 1
    finally:
        cluster.map_all_hosts(dictionary.drop).result()


@pytest.mark.django_db
def test_the_janitor_reaps_past_a_run_it_cannot_reap(cluster: ClickhouseCluster, persons_database):
    # One unreapable run must not shadow the later ones, or they stay stranded on every sweep.
    instance = dagster.DagsterInstance.ephemeral()
    dead_a = instance.create_run_for_job(job_def=clickhouse_deletion_sweep_job, status=dagster.DagsterRunStatus.FAILURE)
    dead_b = instance.create_run_for_job(job_def=clickhouse_deletion_sweep_job, status=dagster.DagsterRunStatus.FAILURE)
    first, second = sorted([dead_a.run_id, dead_b.run_id])
    dict_first = _foreign_run_dictionary(cluster, first)
    _foreign_run_dictionary(cluster, second)

    real = clickhouse_cleanup._kill_and_drop_run_assets

    def fail_on_first(cluster_arg, run_id):
        if run_id == first.replace("-", "_"):
            raise RuntimeError("unreapable")
        return real(cluster_arg, run_id)

    try:
        with patch.object(clickhouse_cleanup, "_kill_and_drop_run_assets", side_effect=fail_on_first):
            result = run_job(cluster, persons_database, instance=instance)
        assert result.success
        assert cluster.any_host(dictionaries_for_run(second)).result() == 0
        assert cluster.any_host(dictionaries_for_run(first)).result() == 1
    finally:
        cluster.map_all_hosts(dict_first.drop).result()


@pytest.mark.django_db
def test_the_janitor_kills_a_stranded_runs_mutations_before_dropping(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    # A canceled run's last mutation keeps retrying server-side. Dropping its dictionary without
    # the kill leaves that mutation failing forever and blocking every later mutation on the
    # table, so the janitor must kill first, exactly like the failure hook.
    instance = dagster.DagsterInstance.ephemeral()
    dead = instance.create_run_for_job(job_def=clickhouse_deletion_sweep_job, status=dagster.DagsterRunStatus.CANCELED)
    dictionary = _foreign_run_dictionary(cluster, dead.run_id)
    runner = clickhouse_cleanup.LightweightDeleteMutationRunner(
        table="person_distinct_id2",
        predicate=(
            f"throwIf(version >= 0, 'stranded sweep') OR isNotNull("
            f"dictGetOrNull({dictionary.qualified_name!r}, 'max_version', (team_id, distinct_id)))"
        ),
    )
    cluster.any_host(runner).result()

    result = run_job(cluster, persons_database, instance=instance)

    assert result.success
    assert cluster.any_host(dictionaries_for_run(dead.run_id)).result() == 0

    def unfinished_mutations(client) -> int:
        [[count]] = client.execute(
            "SELECT count() FROM system.mutations WHERE NOT is_done AND NOT is_killed AND table = %(table)s",
            {"table": "person_distinct_id2"},
        )
        return count

    assert cluster.any_host(unfinished_mutations).result() == 0


@pytest.mark.django_db
def test_a_dry_run_never_dials_postgres(cluster: ClickhouseCluster, persons_database):
    # The EU dry run failed at Postgres resource init on a network path a dry run never needed.
    # Connecting inside the op, after the dry-run return, keeps a dry run ClickHouse-only.
    run = clickhouse_cleanup.CleanupRun.for_run("dry_run_no_pg", clickhouse_cleanup.CleanupConfig(dry_run=True))
    with patch.object(clickhouse_cleanup.psycopg2, "connect", side_effect=AssertionError("dialed postgres")):
        clickhouse_cleanup.persist_deleted_persons(dagster.build_op_context(), cluster, "postgres://unused", run)


@pytest.mark.django_db
def test_a_postgres_connect_failure_drops_the_dictionaries(cluster: ClickhouseCluster, persons_database):
    # A connect failure at resource init happens before the step exists, so the failure hook
    # never ran and the run's dictionaries survived on every host. Connecting inside the op
    # makes it a step failure, and the hook must clean up.
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    real_connect = psycopg2.connect

    def refuse_dsn_connects(*args, **kwargs):

        # Only the op passes a single DSN string; Django's own connections use kwargs and must

        # keep working, or the cohort op fails first and the wrong step trips the hook.

        if args and isinstance(args[0], str):
            raise OperationalError("connection timed out")

        return real_connect(*args, **kwargs)

    with patch.object(clickhouse_cleanup.psycopg2, "connect", side_effect=refuse_dsn_connects):
        result = run_job(cluster, persons_database, raise_on_error=False)

    assert not result.success
    assert cluster.any_host(dictionaries_for_run(result.run_id)).result() == 0


@pytest.mark.django_db
def test_a_capped_run_deletes_a_slice_and_the_next_run_drains_the_rest(cluster: ClickhouseCluster, persons_database):
    # max_persons bounds one run's blast radius; correctness across runs holds because whatever
    # the cap excludes keeps its tombstones. Dropping the cap plumbing or making the capped
    # populate non-deterministic breaks the convergence this asserts.
    for _ in range(3):
        create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    capped = {"ops": {"clear_removed_cohort_data": {"config": {"dry_run": False, "max_persons": 2}}}}

    run_job(cluster, persons_database, run_config=capped)
    assert cluster.any_host(visible_persons).result() == 1
    assert len(queued_rows(persons_database)) == 2

    run_job(cluster, persons_database, run_config=capped)
    assert cluster.any_host(visible_persons).result() == 0
    assert len(queued_rows(persons_database)) == 3


@pytest.mark.django_db
def test_a_team_range_limits_the_sweep_to_those_teams(cluster: ClickhouseCluster, persons_database):
    inside = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    outside = create_person(team_id=TEAM_ID + 1, version=0, is_deleted=True)
    ranged = {
        "ops": {
            "clear_removed_cohort_data": {"config": {"dry_run": False, "min_team_id": TEAM_ID, "max_team_id": TEAM_ID}}
        }
    }

    run_job(cluster, persons_database, run_config=ranged)

    assert cluster.any_host(rows_for(inside)).result() == 0
    outside_rows = cluster.any_host(
        lambda client: client.execute(
            "SELECT count() FROM person WHERE team_id = %(t)s AND id = %(id)s",
            {"t": TEAM_ID + 1, "id": outside},
        )[0][0]
    ).result()
    assert outside_rows == 1
    # Cleanup: the out-of-range person is outside the harness truncation scope for TEAM_ID.
    run_job(cluster, persons_database)


@pytest.mark.django_db
def test_a_same_run_retry_rewrites_no_rows(cluster: ClickhouseCluster, persons_database):
    # The upsert's conflict guard skips rows that already hold the incoming values. Without it a
    # Dagster retry of this op writes a new tuple version for every queued person, and a retry
    # over millions of rows leaves that many dead tuples on the persons writer. A full second job
    # run cannot exercise this: the first run hard-deletes the ClickHouse rows, so the op never
    # upserts the same person twice. The op is invoked directly instead, as a retry would.
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    run = clickhouse_cleanup.CleanupRun.for_run("persist_retry_run", clickhouse_cleanup.CleanupConfig(dry_run=False))
    cluster.any_host(run.persons.populate).result()
    cluster.map_all_hosts(run.persons.sync_replica).result()
    run = replace(run, distinct_ids_deleted_at=datetime(2026, 1, 1, tzinfo=UTC), persons_count=1)

    def queue_row() -> tuple:
        # xmin changes on every UPDATE, so a stable xmin proves no new tuple version was written.
        with persons_database.cursor() as cursor:
            cursor.execute(f"SELECT xmin::text, deleted_at, cleaned_at FROM {PG_CLEANUP_QUEUE_TABLE}")
            [row] = cursor.fetchall()
            return row

    clickhouse_cleanup.persist_deleted_persons(dagster.build_op_context(), cluster, persons_db_url(writer=True), run)
    first = queue_row()

    clickhouse_cleanup.persist_deleted_persons(dagster.build_op_context(), cluster, persons_db_url(writer=True), run)
    assert queue_row() == first

    # A drained row must still be re-armed even when deleted_at matches, or the second deletion
    # of a re-created person is dropped.
    with persons_database.cursor() as cursor:
        cursor.execute(f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET cleaned_at = now()")
    persons_database.commit()
    clickhouse_cleanup.persist_deleted_persons(dagster.build_op_context(), cluster, persons_db_url(writer=True), run)
    rearmed = queue_row()
    assert rearmed[2] is None
    assert rearmed[0] != first[0]


@pytest.mark.django_db
def test_excludes_a_person_revived_while_the_run_is_in_flight(cluster: ClickhouseCluster, persons_database):
    revived = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="spared", person_id=revived, version=0)
    doomed = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="gone", person_id=doomed, version=0)

    original = OrphanedDistinctIdsTable.populate

    def revive_then_populate(self, client, persons_dictionary, settings=None):
        # Fires after the snapshot is taken and the dictionary is loaded, so the checkpoint is
        # the only thing standing between the revived person and the delete.
        create_person(uuid=revived, team_id=TEAM_ID, version=10, is_deleted=False)
        return original(self, client, persons_dictionary, settings=settings)

    with patch.object(OrphanedDistinctIdsTable, "populate", revive_then_populate):
        run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == {"spared"}
    assert cluster.any_host(rows_for(doomed)).result() == 0
    assert cluster.any_host(rows_for(revived)).result() > 0
    # The queued set has to match the set deleted in ClickHouse. If they diverge, the Postgres
    # drain clears a person that is still live here.
    assert [str(row[1]) for row in queued_rows(persons_database)] == [doomed]


@pytest.mark.django_db
def test_no_op_when_nothing_is_soft_deleted(cluster: ClickhouseCluster, persons_database):
    # The snapshot is empty, so the dictionary source returns nothing and dictHas never matches.
    live = create_person(team_id=TEAM_ID, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="kept", person_id=live, version=0)

    run_job(cluster, persons_database)

    assert cluster.any_host(visible_persons).result() == 1
    assert cluster.any_host(surviving_distinct_ids).result() == {"kept"}
    assert queued_rows(persons_database) == []


@pytest.mark.django_db
def test_is_idempotent(cluster: ClickhouseCluster, persons_database):
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="gone", person_id=deleted, version=0)
    create_person(team_id=TEAM_ID, version=0)

    run_job(cluster, persons_database)
    # The first run tombstones the deleted rows, so the second snapshot no longer sees them.
    run_job(cluster, persons_database)

    assert cluster.any_host(visible_persons).result() == 1
    assert cluster.any_host(surviving_distinct_ids).result() == set()


@pytest.mark.django_db
def test_dry_run_deletes_nothing(cluster: ClickhouseCluster, persons_database):
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="gone", person_id=deleted, version=0)
    seed_cohort_rows(cluster, count=5)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    run_job(cluster, persons_database, run_config=None)

    assert cluster.any_host(visible_persons).result() == 1
    assert cluster.any_host(surviving_distinct_ids).result() == {"gone"}
    assert cluster.any_host(cohort_rows).result() == 5
    assert queued_rows(persons_database) == []
    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is None


@pytest.mark.django_db
def test_drops_the_dictionaries_and_clears_the_run_rows(cluster: ClickhouseCluster, persons_database):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    result = run_job(cluster, persons_database)

    # A leaked dictionary holds its key set in memory on every host. The rows are cheaper, but the
    # tables are shared, so a run that never clears its own rows makes every later run read them.
    assert cluster.any_host(dictionaries_for_run(result.run_id)).result() == 0
    assert cluster.any_host(snapshot_rows_for_run(result.run_id)).result() == 0


@pytest.mark.django_db
def test_clears_cohort_rows_and_marks_the_deletion_verified_on_the_next_run(
    cluster: ClickhouseCluster, persons_database
):
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    run_job(cluster, persons_database)

    # The mark pass runs before the delete pass, so it sees rows that are still present and
    # verification lands a run later. A reordering that drops the mark pass would leave
    # AsyncDeletion rows unverified forever, and they would be re-swept every week.
    assert cluster.any_host(cohort_rows).result() == 0
    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is None

    run_job(cluster, persons_database)

    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is not None


@pytest.mark.django_db
def test_cohort_delete_pass_runs_when_the_mark_pass_fails(cluster: ClickhouseCluster, persons_database):
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    with patch(
        "posthog.models.async_deletion.delete_cohorts.AsyncCohortDeletion.mark_deletions_done",
        side_effect=Exception("boom"),
    ):
        result = run_job(cluster, persons_database)

    # Collapsing the two guards into one try would skip the pass that actually removes rows.
    assert result.success
    assert cluster.any_host(cohort_rows).result() == 0


@pytest.mark.django_db
def test_cohort_sweep_runs_even_when_the_person_delete_fails(cluster: ClickhouseCluster, persons_database):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    with patch(
        "posthog.dags.clickhouse_cleanup.LightweightDeleteMutationRunner",
        side_effect=Exception("boom"),
    ):
        result = run_job(cluster, persons_database, raise_on_error=False)

    # Moving the cohort sweep back downstream of the person path would strand cohort rows every
    # week that path ran long or failed, which is why it goes first.
    assert not result.success
    assert cluster.any_host(cohort_rows).result() == 0


@pytest.mark.django_db
def test_a_run_ignores_another_runs_snapshot_rows(cluster: ClickhouseCluster, persons_database):
    # Runs share the snapshot tables, so every read of them has to be scoped by run id. Drop any
    # one of those WHERE clauses and this fails: the decoy's worklist rows delete a live person and
    # a live mapping, and its exclusion rows spare the person this run is deleting.
    live = create_person(team_id=TEAM_ID, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="kept", person_id=live, version=0)
    doomed = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="gone", person_id=doomed, version=0)

    seed_decoy_run(cluster, spared_person=live, spared_distinct_id="kept", doomed_person=doomed)

    run_job(cluster, persons_database)

    assert cluster.any_host(rows_for(live)).result() == 1
    assert cluster.any_host(surviving_distinct_ids).result() == {"kept"}
    assert cluster.any_host(rows_for(doomed)).result() == 0
    assert [str(row[1]) for row in queued_rows(persons_database)] == [doomed]
    # Clearing rows at the end of a run has to be scoped too, or one run wipes another's worklist.
    assert cluster.any_host(snapshot_rows_for_run(DECOY_RUN_ID)).result() > 0


@pytest.mark.django_db
def test_a_failed_run_drops_its_dictionaries_and_keeps_its_rows(cluster: ClickhouseCluster, persons_database):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    # Fails once the dictionaries are built, so there is something to strand.
    with patch(
        "posthog.dags.clickhouse_cleanup.LightweightDeleteMutationRunner",
        side_effect=Exception("boom"),
    ):
        result = run_job(cluster, persons_database, raise_on_error=False)

    assert not result.success
    # Dagster skips drop_snapshot_assets after a failure, so without the hook the dictionaries
    # would survive on every host and accumulate across failed runs.
    assert cluster.any_host(dictionaries_for_run(result.run_id)).result() == 0
    # The rows survive on purpose: they cost far less than a dictionary, the tables' TTL reaps
    # them, and they are what makes a failed sweep inspectable in the meantime.
    assert cluster.any_host(snapshot_rows_for_run(result.run_id)).result() > 0


@pytest.mark.django_db
def test_keeps_a_distinct_id_recaptured_while_the_run_is_in_flight(cluster: ClickhouseCluster, persons_database):
    live = create_person(team_id=TEAM_ID, version=0)
    for distinct_id in ("recaptured", "gone"):
        create_person_distinct_id(team_id=TEAM_ID, distinct_id=distinct_id, person_id=live, version=0)
        create_person_distinct_id(
            team_id=TEAM_ID, distinct_id=distinct_id, person_id=live, version=100, is_deleted=True
        )

    original = OrphanedDistinctIdsTable.populate

    def recapture_then_populate(self, client, persons_dictionary, settings=None):
        result = original(self, client, persons_dictionary, settings=settings)
        # A client captures the id again after the snapshot froze the reason it qualified. Trusting
        # that snapshot would delete every version of the mapping, including this live one.
        create_person_distinct_id(team_id=TEAM_ID, distinct_id="recaptured", person_id=live, version=200)
        return result

    with patch.object(OrphanedDistinctIdsTable, "populate", recapture_then_populate):
        run_job(cluster, persons_database)

    assert cluster.any_host(surviving_distinct_ids).result() == {"recaptured"}
    assert cluster.any_host(current_owner("recaptured")).result() == UUID(live)


def versions_for(distinct_id: str):
    def query(client: Client) -> list[int]:
        rows = client.execute(
            "SELECT version FROM person_distinct_id2 WHERE team_id = %(team_id)s AND distinct_id = %(d)s ORDER BY version",
            {"team_id": TEAM_ID, "d": distinct_id},
        )
        return [row[0] for row in rows]

    return query


def current_deleted(distinct_id: str):
    def query(client: Client) -> int | None:
        rows = client.execute(
            """
            SELECT argMax(is_deleted, version) FROM person_distinct_id2
            WHERE team_id = %(team_id)s AND distinct_id = %(d)s GROUP BY distinct_id
            """,
            {"team_id": TEAM_ID, "d": distinct_id},
        )
        return rows[0][0] if rows else None

    return query


@pytest.mark.django_db
def test_an_interrupted_sweep_leaves_the_tombstone_as_the_surviving_version(
    cluster: ClickhouseCluster, persons_database
):
    # The reason the delete is ordered at all. The first pass runs for real; the second is cut off
    # the way a killed or failed mutation would cut it off. The key must still resolve as deleted.
    # Reverse the two passes and this fails: the tombstone goes first and the older live row is
    # handed back to a person the run is about to delete.
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="doomed", person_id=deleted, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="doomed", person_id=deleted, version=100, is_deleted=True)

    real_runner = clickhouse_cleanup.LightweightDeleteMutationRunner
    calls = itertools.count()

    def fail_on_the_second_pass(*args, **kwargs):
        if next(calls) >= 1:
            raise RuntimeError("interrupted between passes")
        return real_runner(*args, **kwargs)

    with patch.object(clickhouse_cleanup, "LightweightDeleteMutationRunner", fail_on_the_second_pass):
        result = run_job(cluster, persons_database, raise_on_error=False)

    assert not result.success
    surviving = cluster.any_host(versions_for("doomed")).result()
    assert surviving == [100], f"expected only the tombstone to survive, got {surviving}"
    assert cluster.any_host(current_deleted("doomed")).result() == 1


@pytest.mark.django_db
def test_removes_every_version_below_the_max_in_one_pass(cluster: ClickhouseCluster, persons_database):
    # Depth must not drive the number of passes: three versions collapse in the same two passes
    # as two do.
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    for version in (0, 5):
        create_person_distinct_id(team_id=TEAM_ID, distinct_id="deep", person_id=deleted, version=version)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="deep", person_id=deleted, version=100, is_deleted=True)

    run_job(cluster, persons_database)

    assert cluster.any_host(versions_for("deep")).result() == []


@pytest.mark.django_db
def test_rows_written_after_the_snapshot_survive(cluster: ClickhouseCluster, persons_database):
    # Both passes are bounded by the snapshot's max_version, so a run never removes a row it did
    # not observe.
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="racing", person_id=deleted, version=0)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="racing", person_id=deleted, version=100, is_deleted=True)

    original = OrphanedDistinctIdsTable.populate

    def write_after_snapshot(self, client, persons_dictionary, settings=None):
        result = original(self, client, persons_dictionary, settings=settings)
        create_person_distinct_id(team_id=TEAM_ID, distinct_id="racing", person_id=deleted, version=500)
        return result

    with patch.object(OrphanedDistinctIdsTable, "populate", write_after_snapshot):
        run_job(cluster, persons_database)

    assert cluster.any_host(versions_for("racing")).result() == [500]


@pytest.mark.django_db
def test_team_ranges_cover_every_candidate_team_exactly_once():
    teams = [3, 1, 9, 4, 7, 2]
    ranges = clickhouse_cleanup._team_ranges(teams, batches=3)

    assert clickhouse_cleanup._team_ranges([], batches=4) == []
    # Contiguous and non-overlapping, so no key falls between two batches.
    assert [r.low for r in ranges] == sorted(r.low for r in ranges)
    for earlier, later in zip(ranges, ranges[1:]):
        assert earlier.high < later.low
    for team in teams:
        assert sum(1 for r in ranges if r.low <= team <= r.high) == 1


@pytest.mark.django_db
def test_more_batches_than_teams_does_not_produce_empty_ranges():
    ranges = clickhouse_cleanup._team_ranges([5, 6], batches=10)
    assert ranges == [clickhouse_cleanup.TeamRange(low=5, high=5), clickhouse_cleanup.TeamRange(low=6, high=6)]


@pytest.mark.django_db
def test_a_retried_snapshot_populate_cannot_skew_the_dictionary(cluster: ClickhouseCluster):
    # An op retry re-runs populate, leaving duplicate key rows until a merge collapses them. The
    # dictionary must read the newest max_version bound, not whichever duplicate it happens upon.
    person = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    table = clickhouse_cleanup.DeletedPersonsTable(run_id="retry_run")
    cluster.any_host(table.populate).result()
    # The person gains a higher deleted version between the attempt and its retry.
    create_person(uuid=person, team_id=TEAM_ID, version=3, is_deleted=True)
    cluster.any_host(table.populate).result()
    cluster.map_all_hosts(table.sync_replica).result()

    dictionary = clickhouse_cleanup.SnapshotDictionary(
        source=table, excluded=clickhouse_cleanup.RevivedPersonsTable(run_id="retry_run")
    )
    try:
        cluster.map_all_hosts(partial(dictionary.create, shards=1, max_execution_time=0, max_memory_usage=0)).result()
        cluster.map_all_hosts(dictionary.load, concurrency=1).result()
        rows = cluster.any_host(
            lambda client: client.execute(f"SELECT person_id, max_version FROM {dictionary.qualified_name}")
        ).result()
        assert rows == [(UUID(person), 3)]
    finally:
        cluster.map_all_hosts(dictionary.drop).result()
        cluster.any_host(table.drop_run_partition).result()


@pytest.mark.django_db
def test_a_reaped_snapshot_fails_the_delete_instead_of_under_deleting(cluster: ClickhouseCluster):
    # The 14-day TTL drops a stalled run's partition; the delete must then fail loudly rather
    # than sweep from a silently shrunken worklist.
    run = clickhouse_cleanup.CleanupRun.for_run("reaped-run", clickhouse_cleanup.CleanupConfig(dry_run=False))
    run = replace(run, persons_count=5)

    with pytest.raises(dagster.Failure, match="snapshot TTL"):
        clickhouse_cleanup.delete_persons(dagster.build_op_context(resources={"cluster": cluster}), run=run)


T0 = datetime(2026, 1, 1, 12, 0, 0)


def failing_status(fail_at: datetime, parts: int = 10, now: datetime | None = None) -> MutationStatus:
    return MutationStatus(
        done=False,
        visible=True,
        parts_to_do=parts,
        latest_fail_time=fail_at,
        latest_fail_reason="boom",
        server_now=now or fail_at,
    )


def quiet_status(parts: int = 10, visible: bool = True) -> MutationStatus:
    return MutationStatus(
        done=False,
        visible=visible,
        parts_to_do=parts,
        latest_fail_time=None,
        latest_fail_reason="",
        server_now=T0,
    )


def test_mutation_progress_tolerates_failures_while_parts_still_complete():
    # ClickHouse retries failed part mutations itself; as long as parts keep completing the run
    # must keep waiting. Reverting to fail-on-any-reason kills a batch that would have finished.
    progress = MutationProgress(stall_timeout=100)
    progress.observe([quiet_status(parts=20)], now=0)
    for tick in range(1, 15):
        progress.observe([failing_status(T0 + timedelta(seconds=tick * 60), parts=20 - tick)], now=tick * 60)


def test_mutation_progress_declares_a_stall_when_failures_recur_without_progress():
    progress = MutationProgress(stall_timeout=100)
    progress.observe([quiet_status(parts=3), quiet_status(parts=10)], now=0)
    progress.observe([quiet_status(parts=3), failing_status(T0 + timedelta(seconds=15))], now=15)
    with pytest.raises(MutationStalled):
        progress.observe([quiet_status(parts=3), failing_status(T0 + timedelta(seconds=120))], now=120)


def test_mutation_progress_ignores_a_failure_that_predates_polling():
    # MutationRunner can re-attach to an existing mutation whose old attempts failed; that history
    # must not condemn a batch that has not failed since.
    stale = T0 - timedelta(hours=6)
    progress = MutationProgress(stall_timeout=100)
    progress.observe([failing_status(stale, now=T0)], now=0)
    progress.observe([failing_status(stale, now=T0 + timedelta(seconds=200))], now=200)
    with pytest.raises(MutationStalled):
        progress.observe([failing_status(T0 + timedelta(seconds=300))], now=300)


def test_mutation_progress_counts_a_failure_just_before_the_first_poll():
    # A freshly enqueued mutation can fail before the first poll lands; unlike a re-attached
    # mutation's stale history, that failure is evidence.
    progress = MutationProgress(stall_timeout=100)
    progress.observe([failing_status(T0 - timedelta(seconds=5), now=T0)], now=0)
    with pytest.raises(MutationStalled):
        progress.observe([failing_status(T0 - timedelta(seconds=5), now=T0 + timedelta(seconds=150))], now=150)


def test_mutation_progress_fails_a_healthy_mutation_past_the_wait_deadline():
    # A mutation blocked behind another mutation is healthy and makes no progress; without the
    # deadline that run waits forever and raises no alert.
    progress = MutationProgress(stall_timeout=600, wait_deadline=1000)
    progress.observe([quiet_status(parts=5)], now=0.0)
    progress.observe([quiet_status(parts=5)], now=999.0)
    with pytest.raises(MutationStalled, match="not finished after 1000"):
        progress.observe([quiet_status(parts=5)], now=1001.0)


def test_mutation_progress_waits_on_a_slow_mutation_that_is_not_failing():
    # No failures means a big part or a busy cluster; declaring that stuck would kill every
    # long-running healthy batch.
    progress = MutationProgress(stall_timeout=100)
    for tick in range(100):
        progress.observe([quiet_status(parts=10)], now=tick * 60)


def test_mutation_progress_tolerates_brief_invisibility_and_fails_when_it_persists():
    # The mutation entry replicates through Keeper, so a lagged replica briefly not knowing it is
    # normal; a replica that never learns of it is not.
    progress = MutationProgress(stall_timeout=100, visibility_timeout=300)
    progress.observe([quiet_status(visible=False)], now=0)
    progress.observe([quiet_status(visible=False)], now=299)
    with pytest.raises(MutationStalled):
        progress.observe([quiet_status(visible=False)], now=301)


@pytest.mark.django_db
def test_a_mutation_that_fails_every_attempt_fails_the_run_and_gets_killed(
    cluster: ClickhouseCluster, persons_database, monkeypatch
):
    deleted = create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person_distinct_id(team_id=TEAM_ID, distinct_id="doomed", person_id=deleted, version=0)

    monkeypatch.setattr(clickhouse_cleanup, "MUTATION_POLL_SECONDS", 0.1)
    real_runner = clickhouse_cleanup.LightweightDeleteMutationRunner

    def poisoned_runner(*args, **kwargs):
        # Fails at part-mutation time on every attempt, not at submission: the predicate reads a
        # column, so ClickHouse cannot constant-fold the throw during validation.
        kwargs["predicate"] = f"throwIf(version >= 0, 'poisoned sweep') OR ({kwargs['predicate']})"
        return real_runner(*args, **kwargs)

    stalling = {"ops": {"clear_removed_cohort_data": {"config": {"dry_run": False, "mutation_stall_timeout": 1}}}}
    with patch.object(clickhouse_cleanup, "LightweightDeleteMutationRunner", poisoned_runner):
        result = run_job(cluster, persons_database, run_config=stalling, raise_on_error=False)

    assert not result.success
    # The poisoned mutation never applied, so the data is intact.
    assert cluster.any_host(surviving_distinct_ids).result() == {"doomed"}

    # The failure hook must kill the stuck mutation, or it retries in the background forever and
    # blocks every later mutation on the table.
    def unfinished_mutations(client: Client) -> int:
        [[count]] = client.execute(
            "SELECT count() FROM system.mutations WHERE NOT is_done AND NOT is_killed AND table = %(table)s",
            {"table": "person_distinct_id2"},
        )
        return count

    assert cluster.any_host(unfinished_mutations).result() == 0
