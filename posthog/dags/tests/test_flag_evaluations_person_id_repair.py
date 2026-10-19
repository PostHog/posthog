from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.flag_evaluations_person_id_repair import (
    FlagEvaluationsPersonIdRepairConfig,
    PersonIdRepairDictionary,
    PersonIdRepairTable,
    flag_evaluations_person_id_repair_job,
)
from posthog.dags.tests.conftest import insert_flag_evaluations
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT

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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dry_run, extra_calls, succeeds, rewritten",
    [
        pytest.param(False, (), True, {STALE.label: PERSON_B}, id="repair"),
        pytest.param(True, (), True, {}, id="dry_run"),
        pytest.param(False, (CONFLICTING_CALL,), False, {}, id="conflicting_events_copies"),
        pytest.param(False, (AGREEING_CALL,), False, {}, id="agreeing_events_copy"),
        pytest.param(False, (OUTSIDE_WINDOW,), True, {STALE.label: PERSON_B}, id="outside_window"),
    ],
)
def test_repair_rewrites_only_imported_rows_that_still_hold_the_stale_id(
    cluster: ClickhouseCluster,
    dry_run: bool,
    extra_calls: tuple[FlagCall, ...],
    succeeds: bool,
    rewritten: dict[str, UUID],
) -> None:
    # nosemgrep: test-datetime-now-without-freeze (the rows and both window bounds are offsets from this one reading, so passing UTC midnight changes no assertion)
    now = datetime.now(UTC)
    calls = (*CALLS, *extra_calls)
    seed(cluster, now, calls)
    config = FlagEvaluationsPersonIdRepairConfig(
        start_date=days_before(now, 5), end_date=days_before(now, 1), dry_run=dry_run
    )

    result = flag_evaluations_person_id_repair_job.execute_in_process(
        run_config=dagster.RunConfig(ops={"plan_person_id_repair": config}),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )

    table = PersonIdRepairTable(id=UUID(result.dagster_run.run_id))
    dictionary = PersonIdRepairDictionary(source=table)
    try:
        assert result.success is succeeds
        expected = {call.label: call.stored_person_id for call in calls} | rewritten
        assert stored_person_ids(cluster, calls) == Counter(expected.items())
        if succeeds:
            assert not any(cluster.map_all_hosts(table.exists).result().values())
            assert not any(cluster.map_all_hosts(dictionary.exists).result().values())
        else:
            assert any(cluster.map_all_hosts(table.exists).result().values())
    finally:
        cluster.map_all_hosts(dictionary.drop).result()
        cluster.map_all_hosts(table.drop).result()
