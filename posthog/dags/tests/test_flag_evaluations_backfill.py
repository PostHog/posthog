import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import dagster
from clickhouse_driver import Client
from dagster._core.remote_origin import RegisteredCodeLocationOrigin, RemoteJobOrigin, RemoteRepositoryOrigin

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.data_deletion_requests import data_deletion_request_property_removal
from posthog.dags.deletes import deletes_job
from posthog.dags.flag_evaluations_backfill import (
    FlagEvaluationsBackfillConfig,
    PolicyDisk,
    ShardBackfill,
    ShardBackfillTotals,
    disk_headroom,
    flag_evaluations_backfill_job,
    resolve_backfill_days,
)
from posthog.dags.person_overrides import squash_person_overrides
from posthog.dags.tests.conftest import insert_flag_evaluations
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_SOURCE_EVENT

TEAM_ONE, TEAM_TWO, TEAM_THREE = 1, 2, 3


@frozen
class SourceEvent:
    label: str
    team_id: int
    age: timedelta
    properties: Mapping[str, object]
    event: str = FLAG_EVALUATIONS_SOURCE_EVENT

    @property
    def uuid(self) -> UUID:
        return uuid5(NAMESPACE_URL, self.label)

    @property
    def distinct_id(self) -> str:
        return f"{self.label}-user"


@frozen
class StoredRow:
    label: str
    flag_key: str
    response: str
    session_id: str
    person_id: UUID
    inserted_at_is_timestamp: bool


def flag_called(label: str, team_id: int, age: timedelta) -> SourceEvent:
    return SourceEvent(
        label=label,
        team_id=team_id,
        age=age,
        properties={
            "$feature_flag": f"{label}-flag",
            "$feature_flag_response": "control",
            "$session_id": f"{label}-session",
        },
    )


def copied(event: SourceEvent) -> StoredRow:
    return StoredRow(
        label=event.label,
        flag_key=str(event.properties["$feature_flag"]),
        response=str(event.properties["$feature_flag_response"]),
        session_id=str(event.properties["$session_id"]),
        person_id=uuid5(NAMESPACE_URL, event.distinct_id),
        inserted_at_is_timestamp=True,
    )


INSIDE_RECENT = flag_called("inside_recent", TEAM_ONE, timedelta(days=2, hours=12))
INSIDE_TEAM_THREE = flag_called("inside_team_three", TEAM_THREE, timedelta(days=30))
INSIDE_OLD = flag_called("inside_old", TEAM_TWO, timedelta(days=60))
ALREADY_FORKED = flag_called("already_forked", TEAM_ONE, timedelta(days=5))

SOURCE_EVENTS = [
    INSIDE_RECENT,
    INSIDE_TEAM_THREE,
    INSIDE_OLD,
    ALREADY_FORKED,
    SourceEvent(
        label="numeric_flag_key",
        team_id=TEAM_ONE,
        age=timedelta(days=3),
        properties={"$feature_flag": 7, "$feature_flag_response": "control", "$session_id": "numeric-session"},
    ),
    SourceEvent(
        label="empty_flag_key",
        team_id=TEAM_ONE,
        age=timedelta(days=3),
        properties={"$feature_flag": "", "$feature_flag_response": "control", "$session_id": "empty-session"},
    ),
    SourceEvent(
        label="missing_flag_key",
        team_id=TEAM_ONE,
        age=timedelta(days=3),
        properties={"$feature_flag_response": "control", "$session_id": "missing-session"},
    ),
    replace(flag_called("other_event", TEAM_ONE, timedelta(days=3)), event="$pageview"),
    flag_called("today", TEAM_ONE, timedelta(0)),
    # Twelve hours before now is always after the start of yesterday, even when UTC midnight passes
    # between seeding and the run. A row from exactly one day ago would move into the window then.
    flag_called("half_a_day_ago", TEAM_ONE, timedelta(hours=12)),
    flag_called("past_retention", TEAM_ONE, timedelta(days=91)),
]

# The job stops unless each Kafka partition in flag_evaluations delivered a row within the
# consumer-lag limit, because only such rows show that the Kafka path has delivered everything up to
# the copy window. Rows with this identity stand in for that traffic. Their ages set the lag that
# the job reads.
KAFKA_PATH_ROW = SourceEvent(label="kafka_path_row", team_id=TEAM_ONE, age=timedelta(0), properties={})

SAME_UUID_OTHER_TEAM = replace(INSIDE_RECENT, team_id=TEAM_TWO)


def forked(event: SourceEvent) -> StoredRow:
    # insert_flag_evaluations writes no properties, so the shard computes empty typed columns for the
    # row. A copied duplicate of the same uuid carries the source event's flag key instead.
    return StoredRow(
        label=event.label,
        flag_key="",
        response="",
        session_id="",
        person_id=uuid5(NAMESPACE_URL, event.distinct_id),
        inserted_at_is_timestamp=True,
    )


DEFAULT_WINDOW_COPIES = (INSIDE_RECENT, INSIDE_TEAM_THREE, INSIDE_OLD)


def seed_source_events(cluster: ClickhouseCluster, now: datetime, events: list[SourceEvent]) -> None:
    rows = [
        (
            event.uuid,
            event.event,
            json.dumps(event.properties),
            now - event.age,
            event.team_id,
            event.distinct_id,
            now - event.age,
            uuid5(NAMESPACE_URL, event.distinct_id),
        )
        for event in events
    ]

    def insert(client: Client) -> None:
        client.execute(
            f"""INSERT INTO {EVENTS_DATA_TABLE()}
            (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id)
            VALUES""",
            rows,
        )

    cluster.any_host_by_role(insert, NodeRole.DATA).result()


def seed_flag_evaluation(cluster: ClickhouseCluster, now: datetime, event: SourceEvent) -> None:
    row = (event.team_id, event.distinct_id, uuid5(NAMESPACE_URL, event.distinct_id), event.uuid, now - event.age)
    cluster.any_host(partial(insert_flag_evaluations, [row])).result()


def seed_kafka_path_row(
    cluster: ClickhouseCluster, now: datetime, age: timedelta = timedelta(0), partition: int = 0
) -> None:
    # The lag check skips rows whose inserted_at equals their timestamp, because the backfill copies
    # rows that way. A Kafka row arrives after its event, so its inserted_at is later.
    inserted_at = now - age
    row = (
        KAFKA_PATH_ROW.team_id,
        KAFKA_PATH_ROW.distinct_id,
        uuid5(NAMESPACE_URL, KAFKA_PATH_ROW.distinct_id),
        KAFKA_PATH_ROW.uuid,
        inserted_at - timedelta(seconds=1),
        inserted_at,
        partition,
    )

    def insert(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_flag_evaluations
            (team_id, distinct_id, person_id, uuid, timestamp, inserted_at, _partition)
            VALUES""",
            [row],
        )

    cluster.any_host(insert).result()


def stored_rows(cluster: ClickhouseCluster) -> Counter[StoredRow]:
    labels = {event.uuid: event.label for event in SOURCE_EVENTS}

    def select(client: Client) -> list[tuple[UUID, str, str, str, UUID, int]]:
        return client.execute(
            """SELECT uuid, flag_key, response, session_id, person_id, inserted_at = timestamp
            FROM flag_evaluations
            WHERE uuid != %(kafka_path_row)s""",
            {"kafka_path_row": KAFKA_PATH_ROW.uuid},
        )

    return Counter(
        StoredRow(
            label=labels.get(uuid, str(uuid)),
            flag_key=flag_key,
            response=response,
            session_id=session_id,
            person_id=person_id,
            inserted_at_is_timestamp=bool(inserted_at_is_timestamp),
        )
        for uuid, flag_key, response, session_id, person_id, inserted_at_is_timestamp in cluster.any_host_by_role(
            select, NodeRole.DATA
        ).result()
    )


def run_backfill(
    cluster: ClickhouseCluster, instance: dagster.DagsterInstance | None = None, **overrides: Any
) -> dagster.ExecuteInProcessResult:
    # The default disk floor exceeds the free space on a development machine, so every run starts
    # with the floor off. An explicit instance keeps the job from seeing squash or deletes runs that
    # other tests left in the shared PostgreSQL-backed instance.
    config = FlagEvaluationsBackfillConfig(**{"min_free_bytes": 0, **overrides})
    return flag_evaluations_backfill_job.execute_in_process(
        run_config=dagster.RunConfig(ops={"plan_flag_evaluations_backfill": config}),
        resources={"cluster": cluster},
        instance=instance or dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def days_before(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).date().isoformat()


def shard_backfill(
    config: FlagEvaluationsBackfillConfig | None = None,
    *,
    instance: dagster.DagsterInstance | None = None,
    run_id: str = "backfill-run",
) -> ShardBackfill:
    # The cluster is a mock, so the default config turns off the parts wait, which queries it.
    return ShardBackfill(
        cluster=MagicMock(),
        shard_num=1,
        config=config or FlagEvaluationsBackfillConfig(max_unmerged_parts=0),
        instance=instance or dagster.DagsterInstance.ephemeral(),
        run_id=run_id,
        log=MagicMock(),
        query_tags=DagsterTags(),
        workload=Workload.DEFAULT,
        node_role=NodeRole.ALL,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "config_for, reported_rows, expected_copies",
    [
        pytest.param(lambda now: {}, [3], DEFAULT_WINDOW_COPIES, id="default_window"),
        pytest.param(lambda now: {}, [3, 0], DEFAULT_WINDOW_COPIES, id="second_run_copies_nothing_new"),
        pytest.param(
            lambda now: {"start_date": days_before(now, 60), "end_date": days_before(now, 30)},
            [1],
            (INSIDE_OLD,),
            id="explicit_window_includes_start_day_and_excludes_end_day",
        ),
        pytest.param(lambda now: {"team_ids": [TEAM_TWO]}, [1], (INSIDE_OLD,), id="team_ids"),
        pytest.param(lambda now: {"team_id_chunks": 3}, [3], DEFAULT_WINDOW_COPIES, id="team_id_chunks"),
        pytest.param(lambda now: {"dry_run": True}, [3], (), id="dry_run"),
    ],
)
def test_backfill_copies_each_eligible_row_in_the_window_exactly_once(
    cluster: ClickhouseCluster,
    config_for: Callable[[datetime], dict[str, Any]],
    reported_rows: list[int],
    expected_copies: tuple[SourceEvent, ...],
) -> None:
    now = datetime.now(UTC)
    seed_source_events(cluster, now, SOURCE_EVENTS)
    seed_flag_evaluation(cluster, now, ALREADY_FORKED)
    seed_flag_evaluation(cluster, now, SAME_UUID_OTHER_TEAM)
    seed_kafka_path_row(cluster, now)

    results = [run_backfill(cluster, **config_for(now)) for _ in reported_rows]

    assert [result.success for result in results] == [True] * len(reported_rows)
    assert [sum(result.output_for_node("backfill_flag_evaluations_shard").values()) for result in results] == (
        reported_rows
    )
    assert stored_rows(cluster) == Counter(
        [forked(ALREADY_FORKED), forked(SAME_UUID_OTHER_TEAM), *(copied(event) for event in expected_copies)]
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "blocking_job, status, run_config",
    [
        pytest.param(squash_person_overrides, dagster.DagsterRunStatus.QUEUED, None, id="queued_squash"),
        pytest.param(deletes_job, dagster.DagsterRunStatus.STARTED, None, id="started_deletes"),
        pytest.param(
            data_deletion_request_property_removal,
            dagster.DagsterRunStatus.STARTED,
            {"ops": {"load_property_removal_request": {"config": {"request_id": "unused"}}}},
            id="started_property_removal",
        ),
    ],
)
def test_backfill_waits_for_an_active_blocking_run_before_copying(
    cluster: ClickhouseCluster,
    blocking_job: dagster.JobDefinition,
    status: dagster.DagsterRunStatus,
    run_config: dict[str, Any] | None,
) -> None:
    now = datetime.now(UTC)
    on_first_copied_day = replace(
        INSIDE_RECENT, age=now - datetime.combine(now.date() - timedelta(days=2), time(12), tzinfo=UTC)
    )
    seed_source_events(cluster, now, [on_first_copied_day])
    seed_kafka_path_row(cluster, now)
    instance = dagster.DagsterInstance.ephemeral()
    # Dagster refuses to store a QUEUED run that has no code location origin.
    origin = RemoteJobOrigin(
        RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("clickhouse"), "__repository__"), blocking_job.name
    )
    blocking_run = instance.create_run_for_job(
        job_def=blocking_job, status=status, run_config=run_config, remote_job_origin=origin
    )
    copies_seen_while_blocked: list[int] = []

    def finish_blocking_run(_seconds: float) -> None:
        run = instance.get_run_by_id(blocking_run.run_id)
        if run is None or run.is_finished:
            return
        copies_seen_while_blocked.append(sum(stored_rows(cluster).values()))
        instance.report_run_canceled(run)

    # The patch replaces time.sleep for every caller in the process. max_unmerged_parts=0 turns off
    # the parts wait, so that the blocking-run poll is the only caller that reaches this fake.
    with patch("posthog.dags.flag_evaluations_backfill.time.sleep", side_effect=finish_blocking_run):
        result = run_backfill(cluster, instance=instance, max_unmerged_parts=0, start_date=days_before(now, 3))

    assert result.success
    assert copies_seen_while_blocked == [0]
    assert stored_rows(cluster) == Counter([copied(on_first_copied_day)])


REPAIR_DELETE = (
    f"DELETE FROM {FLAG_EVALUATIONS_DATA_TABLE} WHERE toDate(timestamp) = '2026-03-10' AND inserted_at = timestamp"
)


@pytest.mark.parametrize(
    "status, created_before_the_check, team_ids, repair",
    [
        pytest.param(dagster.DagsterRunStatus.STARTED, False, None, f"`{REPAIR_DELETE}`", id="started_during_the_copy"),
        pytest.param(
            dagster.DagsterRunStatus.SUCCESS, False, None, f"`{REPAIR_DELETE}`", id="finished_during_the_copy"
        ),
        pytest.param(
            dagster.DagsterRunStatus.STARTED,
            False,
            [TEAM_TWO, TEAM_THREE],
            f"`{REPAIR_DELETE} AND team_id IN ({TEAM_TWO}, {TEAM_THREE})`",
            id="started_during_a_team_scoped_copy",
        ),
        pytest.param(dagster.DagsterRunStatus.NOT_STARTED, False, None, None, id="not_started_yet"),
        pytest.param(dagster.DagsterRunStatus.CANCELED, True, None, None, id="finished_before_the_check"),
    ],
)
def test_backfill_stops_when_a_blocking_run_starts_during_a_copy(
    status: dagster.DagsterRunStatus, created_before_the_check: bool, team_ids: list[int] | None, repair: str | None
) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    backfill = shard_backfill(FlagEvaluationsBackfillConfig(team_ids=team_ids), instance=instance)
    if created_before_the_check:
        instance.create_run_for_job(job_def=deletes_job, status=status)
    check = backfill.wait_for_blocking_runs()
    if not created_before_the_check:
        instance.create_run_for_job(job_def=deletes_job, status=status)

    if repair is None:
        backfill.check_no_blocking_run_started(check, day=date(2026, 3, 10))
    else:
        with pytest.raises(dagster.Failure) as failure:
            backfill.check_no_blocking_run_started(check, day=date(2026, 3, 10))
        assert repair in str(failure.value.description)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "copy_fails", [pytest.param(False, id="copy_succeeds"), pytest.param(True, id="copy_fails_partway")]
)
def test_backfill_names_the_day_when_a_blocking_run_starts_during_its_copy(
    cluster: ClickhouseCluster, copy_fails: bool
) -> None:
    now = datetime.now(UTC)
    seed_source_events(cluster, now, [INSIDE_RECENT])
    seed_kafka_path_row(cluster, now)
    instance = dagster.DagsterInstance.ephemeral()
    copy_day = ShardBackfill.copy_day

    def copy_while_deletes_starts(backfill: ShardBackfill, *args: Any) -> int:
        instance.create_run_for_job(job_def=deletes_job, status=dagster.DagsterRunStatus.STARTED)
        rows = copy_day(backfill, *args)
        if copy_fails:
            raise RuntimeError("the insert stopped partway")
        return rows

    with patch.object(ShardBackfill, "copy_day", autospec=True, side_effect=copy_while_deletes_starts):
        result = run_backfill(cluster, instance=instance, start_date=days_before(now, 3))

    [failure] = result.get_step_failure_events()
    assert failure.step_failure_data.error is not None
    assert "started while" in failure.step_failure_data.error.message


@pytest.mark.parametrize(
    "status, same_run, stops",
    [
        pytest.param(dagster.DagsterRunStatus.STARTED, False, True, id="another_run_executing"),
        pytest.param(dagster.DagsterRunStatus.NOT_STARTED, False, False, id="another_run_not_started"),
        pytest.param(dagster.DagsterRunStatus.STARTED, True, False, id="only_this_run_executing"),
    ],
)
def test_backfill_stops_before_copying_when_another_backfill_run_is_executing(
    status: dagster.DagsterRunStatus, same_run: bool, stops: bool
) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    other_run = instance.create_run_for_job(job_def=flag_evaluations_backfill_job, status=status)
    backfill = shard_backfill(instance=instance, run_id=other_run.run_id if same_run else "backfill-run")
    yesterday = datetime.now(UTC).date() - timedelta(days=1)

    with (
        patch.object(ShardBackfill, "check_disk_headroom"),
        patch.object(ShardBackfill, "check_consumer_lag"),
        patch.object(ShardBackfill, "copy_day", return_value=0) as copy_day,
    ):
        if stops:
            with pytest.raises(dagster.Failure, match=other_run.run_id):
                backfill.run([yesterday])
        else:
            backfill.run([yesterday])

    assert copy_day.called is not stops


# The earliest day the TTL keeps is 2025-12-11 on 2026-03-10, and 2025-12-12 on 2026-03-11.
@pytest.mark.parametrize(
    "start, step, step_day, effect",
    [
        pytest.param(
            datetime(2026, 3, 10, 23, tzinfo=UTC),
            "copy_day",
            date(2026, 3, 9),
            "pass_midnight",
            id="midnight_passes_during_the_previous_copy",
        ),
        pytest.param(
            datetime(2026, 3, 10, 23, tzinfo=UTC),
            "wait_for_parts_to_merge",
            date(2025, 12, 11),
            "pass_midnight",
            id="midnight_passes_during_the_waits_before_the_copy",
        ),
        pytest.param(
            datetime(2026, 3, 11, 1, tzinfo=UTC),
            "wait_for_parts_to_merge",
            date(2025, 12, 11),
            "fail",
            id="day_expired_before_its_waits",
        ),
    ],
)
def test_backfill_stops_at_the_first_expired_day(start: datetime, step: str, step_day: date, effect: str) -> None:
    days = [date(2026, 3, 9), date(2025, 12, 12), date(2025, 12, 11)]

    with time_machine.travel(start, tick=False) as traveller:

        def patched(name: str) -> Callable[..., int]:
            def run_step(day: date, *args: Any) -> int:
                if (name, day) == (step, step_day):
                    if effect == "fail":
                        raise dagster.Failure(description=f"{name} failed for {day}")
                    traveller.shift(timedelta(hours=2))
                return 5

            return run_step

        with (
            patch.object(ShardBackfill, "wait_for_parts_to_merge", side_effect=patched("wait_for_parts_to_merge")),
            patch.object(ShardBackfill, "check_disk_headroom"),
            patch.object(ShardBackfill, "check_consumer_lag"),
            patch.object(ShardBackfill, "copy_day", side_effect=patched("copy_day")) as copy_day,
        ):
            totals = shard_backfill().run(days)

    assert [call.args[0] for call in copy_day.call_args_list] == days[:2]
    assert totals == ShardBackfillTotals(days=2, rows=10)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides, kafka_path_row_ages",
    [
        pytest.param({"min_free_bytes": 1 << 60}, [timedelta(0)], id="free_space_below_the_floor"),
        pytest.param(
            {"max_consumer_lag_seconds": 3600}, [timedelta(hours=2)], id="kafka_path_behind_by_more_than_the_limit"
        ),
        pytest.param({}, [timedelta(0), timedelta(days=2)], id="one_kafka_partition_silent_for_over_a_day"),
        pytest.param({}, [timedelta(days=8)], id="kafka_path_silent_for_the_whole_lookback"),
    ],
)
def test_backfill_fails_without_copying_when_a_safety_check_fails(
    cluster: ClickhouseCluster, overrides: dict[str, Any], kafka_path_row_ages: list[timedelta]
) -> None:
    now = datetime.now(UTC)
    seed_source_events(cluster, now, [INSIDE_RECENT])
    for partition, age in enumerate(kafka_path_row_ages):
        seed_kafka_path_row(cluster, now, age=age, partition=partition)

    result = run_backfill(cluster, **overrides)

    assert not result.success
    assert stored_rows(cluster) == Counter()


@pytest.mark.parametrize(
    "disks, usable_bytes, below_move_line",
    [
        pytest.param(
            [
                PolicyDisk(volume_priority=1, move_factor=0.1, free_bytes=300, total_bytes=1000),
                PolicyDisk(volume_priority=2, move_factor=0.1, free_bytes=500, total_bytes=2000),
            ],
            700,
            False,
            id="hot_volume_keeps_its_move_reserve",
        ),
        pytest.param(
            [
                PolicyDisk(volume_priority=1, move_factor=0.1, free_bytes=50, total_bytes=1000),
                PolicyDisk(volume_priority=2, move_factor=0.1, free_bytes=5000, total_bytes=8000),
            ],
            4950,
            True,
            id="hot_volume_below_its_move_line",
        ),
        pytest.param(
            [PolicyDisk(volume_priority=1, move_factor=0.1, free_bytes=50, total_bytes=1000)],
            50,
            False,
            id="single_volume_has_no_move_line",
        ),
    ],
)
def test_disk_headroom_leaves_out_the_share_the_mover_keeps_free(
    disks: list[PolicyDisk], usable_bytes: int, below_move_line: bool
) -> None:
    headroom = disk_headroom(disks)

    assert (headroom.usable_bytes, headroom.below_move_line) == (usable_bytes, below_move_line)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"end_date": "2026-03-10"}, id="end_date_after_yesterday"),
        pytest.param({"start_date": "2026-03-01", "end_date": "2026-03-01"}, id="empty_window"),
        pytest.param({"start_date": "2025-12-10"}, id="start_date_already_expired"),
    ],
)
def test_resolve_backfill_days_rejects_an_unsafe_window(overrides: dict[str, Any]) -> None:
    with pytest.raises(dagster.Failure):
        resolve_backfill_days(FlagEvaluationsBackfillConfig(**overrides), today=date(2026, 3, 10))


@pytest.mark.parametrize(
    "overrides, newest, oldest, count",
    [
        pytest.param(
            {"start_date": "2026-03-06", "end_date": "2026-03-09"}, date(2026, 3, 8), date(2026, 3, 6), 3, id="explicit"
        ),
        pytest.param({}, date(2026, 3, 8), date(2025, 12, 11), 88, id="default"),
    ],
)
def test_resolve_backfill_days_lists_each_day_newest_first(
    overrides: dict[str, Any], newest: date, oldest: date, count: int
) -> None:
    days = resolve_backfill_days(FlagEvaluationsBackfillConfig(**overrides), today=date(2026, 3, 10))

    assert (days[0], days[-1], len(days)) == (newest, oldest, count)
