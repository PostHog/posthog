from uuid import UUID

import pytest
from unittest.mock import patch

from clickhouse_driver import Client

from posthog.clickhouse.cleanup_snapshots import CLEANUP_DELETED_PERSONS_TABLE
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.clickhouse_cleanup import DeletedPersonsDictionary, clickhouse_deletion_sweep_job
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.util import create_person

TEAM_ID = 4242
COHORT_ID = 77

# dry_run is declared on the first op alone, which is what stops a launch from setting it on one
# op and missing another.
RUN_FOR_REAL = {"ops": {"clear_removed_cohort_data": {"config": {"dry_run": False}}}}


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


def cohort_rows(client: Client) -> int:
    [[count]] = client.execute("SELECT count() FROM cohortpeople WHERE team_id = %(team_id)s", {"team_id": TEAM_ID})
    return count


def snapshot_rows(client: Client) -> int:
    # The snapshot table is created by migration and outlives every run, so what a run has to clean
    # up is its rows rather than the table. Anchored to the constant, not to a literal that can
    # drift out of step with a rename.
    [[rows]] = client.execute(f"SELECT count() FROM {CLEANUP_DELETED_PERSONS_TABLE}")
    return rows


def leftover_dictionaries(client: Client) -> int:
    [[dictionaries]] = client.execute(
        "SELECT count() FROM system.dictionaries WHERE name LIKE %(pattern)s",
        {"pattern": f"{CLEANUP_DELETED_PERSONS_TABLE}\\_%"},
    )
    return dictionaries


def seed_cohort_rows(cluster: ClickhouseCluster, count: int) -> None:
    rows = [(TEAM_ID, UUID(int=i), COHORT_ID, 1) for i in range(count)]
    cluster.any_host(
        lambda client: client.execute("INSERT INTO cohortpeople (team_id, person_id, cohort_id, sign) VALUES", rows)
    ).result()


def versions_for(person_uuid: str):
    def query(client: Client) -> list[int]:
        rows = client.execute(
            "SELECT version FROM person WHERE team_id = %(team_id)s AND id = %(id)s ORDER BY version",
            {"team_id": TEAM_ID, "id": person_uuid},
        )
        return [row[0] for row in rows]

    return query


@pytest.mark.django_db
def test_a_person_version_written_after_the_snapshot_survives(cluster: ClickhouseCluster):
    # The delete is bounded by the version the snapshot observed. A client can recapture a deleted
    # distinct id mid-run, which writes a live person version the run never saw; dropping the bound
    # sweeps that new state away with the old.
    doomed = create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    original = DeletedPersonsDictionary.load

    def revive_after_snapshot(self, client, timeout_seconds):
        result = original(self, client, timeout_seconds)
        create_person(uuid=doomed, team_id=TEAM_ID, version=500, is_deleted=False)
        return result

    with patch.object(DeletedPersonsDictionary, "load", revive_after_snapshot):
        clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    assert cluster.any_host(versions_for(doomed)).result() == [500]


@pytest.mark.django_db
def test_deletes_soft_deleted_persons_and_preserves_the_rest(cluster: ClickhouseCluster):
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

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

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
def test_no_op_when_nothing_is_soft_deleted(cluster: ClickhouseCluster):
    # The snapshot is empty, so the dictionary source returns nothing and dictHas never matches.
    create_person(team_id=TEAM_ID, version=0)

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    assert cluster.any_host(visible_persons).result() == 1


@pytest.mark.django_db
def test_is_idempotent(cluster: ClickhouseCluster):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    create_person(team_id=TEAM_ID, version=0)

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})
    # The first run tombstones the deleted rows, so the second snapshot no longer sees them.
    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    assert cluster.any_host(visible_persons).result() == 1


@pytest.mark.django_db
def test_dry_run_deletes_nothing(cluster: ClickhouseCluster):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    seed_cohort_rows(cluster, count=5)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    clickhouse_deletion_sweep_job.execute_in_process(resources={"cluster": cluster})

    assert cluster.any_host(visible_persons).result() == 1
    assert cluster.any_host(cohort_rows).result() == 5
    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is None


@pytest.mark.django_db
def test_drops_the_dictionary_and_clears_the_run_rows(cluster: ClickhouseCluster):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    # A leaked dictionary holds the key set in memory on every host. The rows are cheaper, but the
    # table is shared now, so a run that never clears its own rows makes every later run read them.
    assert cluster.any_host(leftover_dictionaries).result() == 0
    assert cluster.any_host(snapshot_rows).result() == 0


@pytest.mark.django_db
def test_clears_cohort_rows_and_marks_the_deletion_verified_on_the_next_run(cluster: ClickhouseCluster):
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    # The mark pass runs before the delete pass, so it sees rows that are still present and
    # verification lands a run later. A reordering that drops the mark pass would leave
    # AsyncDeletion rows unverified forever, and they would be re-swept every week.
    assert cluster.any_host(cohort_rows).result() == 0
    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is None

    clickhouse_deletion_sweep_job.execute_in_process(run_config=RUN_FOR_REAL, resources={"cluster": cluster})

    assert AsyncDeletion.objects.get(team_id=TEAM_ID).delete_verified_at is not None


@pytest.mark.django_db
def test_cohort_delete_pass_runs_when_the_mark_pass_fails(cluster: ClickhouseCluster):
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    with patch(
        "posthog.models.async_deletion.delete_cohorts.AsyncCohortDeletion.mark_deletions_done",
        side_effect=Exception("boom"),
    ):
        result = clickhouse_deletion_sweep_job.execute_in_process(
            run_config=RUN_FOR_REAL, resources={"cluster": cluster}
        )

    # Collapsing the two guards into one try would skip the pass that actually removes rows.
    assert result.success
    assert cluster.any_host(cohort_rows).result() == 0


@pytest.mark.django_db
def test_cohort_sweep_runs_even_when_the_person_delete_fails(cluster: ClickhouseCluster):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)
    seed_cohort_rows(cluster, count=10)
    AsyncDeletion.objects.create(deletion_type=DeletionType.Cohort_full, team_id=TEAM_ID, key=f"{COHORT_ID}_0")

    with patch(
        "posthog.dags.clickhouse_cleanup.LightweightDeleteMutationRunner",
        side_effect=Exception("boom"),
    ):
        result = clickhouse_deletion_sweep_job.execute_in_process(
            run_config=RUN_FOR_REAL, resources={"cluster": cluster}, raise_on_error=False
        )

    # Moving the cohort sweep back downstream of the person delete would strand cohort rows every
    # week the person mutation ran long or failed, which is why it goes first.
    assert not result.success
    assert cluster.any_host(cohort_rows).result() == 0


@pytest.mark.django_db
def test_a_failed_run_drops_its_dictionary_and_keeps_its_rows(cluster: ClickhouseCluster):
    create_person(team_id=TEAM_ID, version=0, is_deleted=True)

    # Fails once the dictionary is built, so there is something to strand.
    with patch(
        "posthog.dags.clickhouse_cleanup.LightweightDeleteMutationRunner",
        side_effect=Exception("boom"),
    ):
        result = clickhouse_deletion_sweep_job.execute_in_process(
            run_config=RUN_FOR_REAL, resources={"cluster": cluster}, raise_on_error=False
        )

    assert not result.success
    # Dagster skips drop_snapshot_assets after a failure, so without the hook the dictionary
    # would survive on every host and accumulate across failed runs.
    assert cluster.any_host(leftover_dictionaries).result() == 0
    # The rows survive on purpose: they cost far less than a dictionary, the table's TTL reaps
    # them, and they are what makes a failed sweep inspectable in the meantime.
    assert cluster.any_host(snapshot_rows).result() > 0
