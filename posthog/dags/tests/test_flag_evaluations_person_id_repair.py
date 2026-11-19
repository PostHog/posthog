from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from unittest.mock import patch

import dagster

from posthog.clickhouse.cluster import (
    AlterTableMutationRunner,
    ClickhouseCluster,
    NodeRole,
    Query,
    wait_for_mutations_on_shards,
)
from posthog.dags import flag_evaluations_person_id_repair
from posthog.dags.deletes import deletes_job
from posthog.dags.flag_evaluations_person_id_repair import (
    FlagEvaluationsPersonIdRepairConfig,
    PersonIdRepairDictionary,
    PersonIdRepairTable,
    RepairRunConfig,
    cleanup_orphaned_flag_evaluations_person_id_repair,
    flag_evaluations_person_id_repair_job,
)
from posthog.dags.tests.conftest import insert_flag_evaluations
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_SOURCE_EVENT

TEAM_ID = 1
DISTINCT_ID = "repair-user"
PERSON_A, PERSON_B, PERSON_C, PERSON_D = (UUID(int=n) for n in range(1, 5))


@frozen
class FlagCall:
    label: str
    stored_person_id: UUID
    events_person_id: UUID
    imported: bool = True
    age: timedelta = timedelta(days=3)

    @property
    def uuid(self) -> UUID:
        return uuid5(NAMESPACE_URL, self.label)

    def timestamp(self, now: datetime) -> datetime:
        return now - self.age


STALE = FlagCall(label="stale", stored_person_id=PERSON_A, events_person_id=PERSON_B)
KAFKA_PATH = FlagCall(label="kafka_path", stored_person_id=PERSON_A, events_person_id=PERSON_B, imported=False)
MOVED_BY_LATER_SQUASH = FlagCall(label="moved_by_later_squash", stored_person_id=PERSON_C, events_person_id=PERSON_C)
CALLS = (STALE, KAFKA_PATH, MOVED_BY_LATER_SQUASH)

# A second events copy of STALE's call would share its sort key. A merge would then collapse the two copies.
# A separate call gives the key (TEAM_ID, DISTINCT_ID, PERSON_A) a second events person_id without that risk.
CONFLICTING_CALL = FlagCall(label="conflicting_call", stored_person_id=PERSON_A, events_person_id=PERSON_D)
# A day other than STALE's, because the build validates each day on its own.
AGREEING_CALL = FlagCall(
    label="agreeing_call", stored_person_id=PERSON_A, events_person_id=PERSON_A, age=timedelta(days=4)
)
OUTSIDE_WINDOW = FlagCall(
    label="outside_window", stored_person_id=PERSON_A, events_person_id=PERSON_C, age=timedelta(days=7)
)
# With STALE this maps A to B and B to C, so B is both a target and a stale key.
CHAINED_CALL = FlagCall(label="chained_call", stored_person_id=PERSON_B, events_person_id=PERSON_C)

WINDOW_START_DAYS_AGO, WINDOW_END_DAYS_AGO = 5, 1


def seed(cluster: ClickhouseCluster, now: datetime, calls: Sequence[FlagCall]) -> None:
    imported_rows = [
        (TEAM_ID, DISTINCT_ID, call.stored_person_id, call.uuid, call.timestamp(now)) for call in calls if call.imported
    ]
    cluster.any_host(partial(insert_flag_evaluations, imported_rows)).result()

    # A row from Kafka arrives after its event, so its inserted_at is later than its timestamp.
    # Its offset is 1 because the imported-row filter treats offset 0 in partition 0 as an import.
    kafka_rows = []
    for call in calls:
        if not call.imported:
            kafka_time = call.timestamp(now) + timedelta(seconds=1)
            kafka_rows.append(
                (
                    TEAM_ID,
                    DISTINCT_ID,
                    call.stored_person_id,
                    call.uuid,
                    call.timestamp(now),
                    kafka_time,
                    kafka_time,
                    0,
                    1,
                )
            )
    cluster.any_host(
        Query(
            """INSERT INTO writable_flag_evaluations
            (team_id, distinct_id, person_id, uuid, timestamp, inserted_at, _timestamp, _partition, _offset)
            VALUES""",
            kafka_rows,
        )
    ).result()

    events_rows = [
        (
            call.uuid,
            FLAG_EVALUATIONS_SOURCE_EVENT,
            "{}",
            call.timestamp(now),
            TEAM_ID,
            DISTINCT_ID,
            call.timestamp(now),
            call.events_person_id,
            "{}",
            call.timestamp(now),
            "full",
            call.timestamp(now),
        )
        for call in calls
    ]
    cluster.any_host_by_role(
        Query(
            f"""INSERT INTO {EVENTS_DATA_TABLE()}
            (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id,
             person_properties, person_created_at, person_mode, _timestamp)
            VALUES""",
            events_rows,
        ),
        NodeRole.DATA,
    ).result()


def stored_person_ids(cluster: ClickhouseCluster, calls: Sequence[FlagCall]) -> Counter[tuple[str, UUID]]:
    labels = {call.uuid: call.label for call in calls}
    rows = cluster.any_host_by_role(Query("SELECT uuid, person_id FROM flag_evaluations"), NodeRole.DATA).result()
    return Counter((labels.get(uuid, str(uuid)), person_id) for uuid, person_id in rows)


def days_before(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).date().isoformat()


def run_repair(
    cluster: ClickhouseCluster, now: datetime, instance: dagster.DagsterInstance | None = None, **overrides: Any
) -> dagster.ExecuteInProcessResult:
    config = FlagEvaluationsPersonIdRepairConfig(
        start_date=days_before(now, WINDOW_START_DAYS_AGO), end_date=days_before(now, WINDOW_END_DAYS_AGO), **overrides
    )
    return flag_evaluations_person_id_repair_job.execute_in_process(
        run_config=dagster.RunConfig(ops={"plan_person_id_repair": config}),
        resources={"cluster": cluster},
        instance=instance or dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def run_cleanup(cluster: ClickhouseCluster, run_id: UUID) -> dagster.ExecuteInProcessResult:
    return cleanup_orphaned_flag_evaluations_person_id_repair.execute_in_process(
        run_config=dagster.RunConfig(ops={"get_repair_dictionary_for_run": RepairRunConfig(run_id=str(run_id))}),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def on_any_host(cluster: ClickhouseCluster, fn: Any) -> bool:
    return any(cluster.map_all_hosts(fn).result().values())


def drop_repair_resources(cluster: ClickhouseCluster, run_id: UUID) -> None:
    dictionary = PersonIdRepairDictionary(source=PersonIdRepairTable(id=run_id))
    cluster.map_all_hosts(dictionary.drop).result()
    cluster.map_all_hosts(dictionary.source.drop).result()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dry_run, extra_calls, runs, succeeds, rewritten",
    [
        # The second run must change nothing the first one left.
        pytest.param(False, (), 2, True, {STALE.label: PERSON_B}, id="repair"),
        pytest.param(True, (), 1, True, {}, id="dry_run"),
        pytest.param(False, (CONFLICTING_CALL,), 1, False, {}, id="conflicting_events_copies"),
        pytest.param(False, (AGREEING_CALL,), 1, False, {}, id="agreeing_events_copy"),
        pytest.param(False, (CHAINED_CALL,), 1, False, {}, id="chained_targets"),
        pytest.param(False, (OUTSIDE_WINDOW,), 1, True, {STALE.label: PERSON_B}, id="outside_window"),
    ],
)
def test_repair_rewrites_only_imported_rows_that_still_hold_the_stale_id(
    cluster: ClickhouseCluster,
    dry_run: bool,
    extra_calls: tuple[FlagCall, ...],
    runs: int,
    succeeds: bool,
    rewritten: dict[str, UUID],
) -> None:
    # nosemgrep: test-datetime-now-without-freeze (the rows and both window bounds are offsets from this one reading, so passing UTC midnight changes no assertion)
    now = datetime.now(UTC)
    calls = (*CALLS, *extra_calls)
    seed(cluster, now, calls)

    results = [run_repair(cluster, now, dry_run=dry_run) for _ in range(runs)]

    run_ids = [UUID(result.dagster_run.run_id) for result in results]
    try:
        assert [result.success for result in results] == [succeeds] * runs
        expected = {call.label: call.stored_person_id for call in calls} | rewritten
        assert stored_person_ids(cluster, calls) == Counter(expected.items())
        for run_id in run_ids:
            table = PersonIdRepairTable(id=run_id)
            dictionary = PersonIdRepairDictionary(source=table)
            assert on_any_host(cluster, table.exists) is not succeeds
            if succeeds:
                assert not on_any_host(cluster, dictionary.exists)
    finally:
        for run_id in run_ids:
            drop_repair_resources(cluster, run_id)


@pytest.mark.django_db
def test_repair_stops_before_the_mutation_when_a_deletes_run_starts_during_the_build(
    cluster: ClickhouseCluster,
) -> None:
    # nosemgrep: test-datetime-now-without-freeze (the rows and both window bounds are offsets from this one reading, so passing UTC midnight changes no assertion)
    now = datetime.now(UTC)
    seed(cluster, now, CALLS)
    instance = dagster.DagsterInstance.ephemeral()
    on_shard_host = flag_evaluations_person_id_repair.on_shard_host

    def start_a_deletes_run(*args: Any, **kwargs: Any) -> int:
        instance.create_run_for_job(job_def=deletes_job, status=dagster.DagsterRunStatus.STARTED)
        return on_shard_host(*args, **kwargs)

    with patch.object(flag_evaluations_person_id_repair, "on_shard_host", side_effect=start_a_deletes_run):
        result = run_repair(cluster, now, instance=instance)

    run_id = UUID(result.dagster_run.run_id)
    try:
        [failure] = result.get_step_failure_events()
        assert failure.step_failure_data.error is not None
        assert "started after the repair read person_id" in failure.step_failure_data.error.message
        assert stored_person_ids(cluster, CALLS) == Counter((call.label, call.stored_person_id) for call in CALLS)
        assert not on_any_host(cluster, PersonIdRepairTable(id=run_id).exists)
        assert not on_any_host(cluster, PersonIdRepairDictionary(source=PersonIdRepairTable(id=run_id)).exists)
    finally:
        drop_repair_resources(cluster, run_id)


@pytest.mark.django_db
def test_cleanup_refuses_while_a_repair_mutation_is_unfinished(cluster: ClickhouseCluster) -> None:
    # nosemgrep: test-datetime-now-without-freeze (the row and the mutation's window are offsets from this one reading, so passing UTC midnight changes no assertion)
    now = datetime.now(UTC)
    seed(cluster, now, (STALE,))
    table = PersonIdRepairTable(id=uuid4())
    dictionary = PersonIdRepairDictionary(source=table)
    runner = AlterTableMutationRunner(
        table=FLAG_EVALUATIONS_DATA_TABLE,
        commands={dictionary.update_command(filter_team_ids=False)},
        parameters={
            "name": dictionary.qualified_name,
            "window_start": f"{days_before(now, WINDOW_START_DAYS_AGO)} 00:00:00",
            "window_end": f"{days_before(now, WINDOW_END_DAYS_AGO)} 00:00:00",
        },
        # The test client otherwise waits for the mutation, which the stopped merges hold open.
        settings={"mutations_sync": 0},
    )
    # Stopped merges also stop mutations, which leaves this one unfinished on every replica.
    start_merges = Query(f"SYSTEM START MERGES {FLAG_EVALUATIONS_DATA_TABLE}")
    try:
        cluster.map_all_hosts(table.create).result()
        cluster.map_all_hosts(partial(dictionary.create, shards=1, max_execution_time=0, max_memory_usage=0)).result()
        cluster.map_all_hosts(dictionary.load).result()
        cluster.map_all_hosts(Query(f"SYSTEM STOP MERGES {FLAG_EVALUATIONS_DATA_TABLE}")).result()
        mutations = runner.enqueue_on_shards(cluster)

        assert not run_cleanup(cluster, table.id).success
        assert on_any_host(cluster, dictionary.exists)

        cluster.map_all_hosts(start_merges).result()
        wait_for_mutations_on_shards(cluster, mutations)

        assert run_cleanup(cluster, table.id).success
        assert not on_any_host(cluster, dictionary.exists)
        assert not on_any_host(cluster, table.exists)
    finally:
        cluster.map_all_hosts(start_merges).result()
        drop_repair_resources(cluster, table.id)
