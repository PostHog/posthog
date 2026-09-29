import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
    disk_headroom,
    flag_evaluations_backfill_job,
    resolve_backfill_days,
)
from posthog.dags.person_overrides import squash_person_overrides
from posthog.dags.tests.conftest import insert_flag_evaluations
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT

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

# The job stops unless flag_evaluations holds a row inserted within the consumer-lag limit, because
# only such a row shows that the Kafka path has delivered everything up to the copy window. This
# row stands in for that traffic, and its age sets the lag that the job reads.
KAFKA_PATH_ROW = SourceEvent(label="kafka_path_row", team_id=TEAM_ONE, age=timedelta(0), properties={})

# insert_flag_evaluations writes no properties, so the shard computes empty typed columns for this
# row. A copied duplicate of the same uuid carries the source event's flag key instead.
FORKED_ROW = StoredRow(
    label=ALREADY_FORKED.label, flag_key="", response="", session_id="", inserted_at_is_timestamp=True
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


def stored_rows(cluster: ClickhouseCluster) -> Counter[StoredRow]:
    labels = {event.uuid: event.label for event in SOURCE_EVENTS}

    def select(client: Client) -> list[tuple[UUID, str, str, str, int]]:
        return client.execute(
            """SELECT uuid, flag_key, response, session_id, inserted_at = timestamp
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
            inserted_at_is_timestamp=bool(inserted_at_is_timestamp),
        )
        for uuid, flag_key, response, session_id, inserted_at_is_timestamp in cluster.any_host_by_role(
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "config_for, runs, expected_copies",
    [
        pytest.param(lambda now: {}, 1, DEFAULT_WINDOW_COPIES, id="default_window"),
        pytest.param(lambda now: {}, 2, DEFAULT_WINDOW_COPIES, id="second_run_copies_nothing_new"),
        pytest.param(
            lambda now: {"start_date": days_before(now, 60), "end_date": days_before(now, 30)},
            1,
            (INSIDE_OLD,),
            id="explicit_window_includes_start_day_and_excludes_end_day",
        ),
        pytest.param(lambda now: {"team_ids": [TEAM_TWO]}, 1, (INSIDE_OLD,), id="team_ids"),
        pytest.param(lambda now: {"team_id_chunks": 3}, 1, DEFAULT_WINDOW_COPIES, id="team_id_chunks"),
        pytest.param(lambda now: {"dry_run": True}, 1, (), id="dry_run"),
    ],
)
def test_backfill_copies_each_eligible_row_in_the_window_exactly_once(
    cluster: ClickhouseCluster,
    config_for: Callable[[datetime], dict[str, Any]],
    runs: int,
    expected_copies: tuple[SourceEvent, ...],
) -> None:
    now = datetime.now(UTC)
    seed_source_events(cluster, now, SOURCE_EVENTS)
    seed_flag_evaluation(cluster, now, ALREADY_FORKED)
    seed_flag_evaluation(cluster, now, KAFKA_PATH_ROW)

    results = [run_backfill(cluster, **config_for(now)) for _ in range(runs)]

    assert [result.success for result in results] == [True] * runs
    assert stored_rows(cluster) == Counter([FORKED_ROW, *(copied(event) for event in expected_copies)])


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
    seed_source_events(cluster, now, [INSIDE_RECENT])
    seed_flag_evaluation(cluster, now, KAFKA_PATH_ROW)
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
    assert stored_rows(cluster) == Counter([copied(INSIDE_RECENT)])


@pytest.mark.parametrize(
    "status, since_offset, stops",
    [
        pytest.param(dagster.DagsterRunStatus.STARTED, timedelta(minutes=-1), True, id="started_during_the_copy"),
        pytest.param(dagster.DagsterRunStatus.SUCCESS, timedelta(minutes=-1), True, id="finished_during_the_copy"),
        pytest.param(dagster.DagsterRunStatus.NOT_STARTED, timedelta(minutes=-1), False, id="not_started_yet"),
        pytest.param(dagster.DagsterRunStatus.STARTED, timedelta(minutes=1), False, id="created_before_the_copy"),
    ],
)
def test_backfill_stops_when_a_blocking_run_starts_during_a_copy(
    status: dagster.DagsterRunStatus, since_offset: timedelta, stops: bool
) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    instance.create_run_for_job(job_def=deletes_job, status=status)
    backfill = ShardBackfill(
        cluster=MagicMock(),
        shard_num=1,
        config=FlagEvaluationsBackfillConfig(),
        instance=instance,
        run_id="backfill-run",
        log=MagicMock(),
        query_tags=DagsterTags(),
        workload=Workload.DEFAULT,
        node_role=NodeRole.ALL,
    )

    check = partial(
        backfill.check_no_blocking_run_started, since=datetime.now(UTC) + since_offset, day=date(2026, 3, 10)
    )

    if stops:
        with pytest.raises(dagster.Failure):
            check()
    else:
        check()


@pytest.mark.parametrize(
    "created_during",
    [
        pytest.param("wait_scan", id="created_while_the_wait_scans_other_jobs"),
        pytest.param("failed_copy", id="created_during_a_copy_that_fails_partway"),
    ],
)
def test_backfill_stops_when_a_blocking_run_is_created_after_the_wait_starts_its_scan(created_during: str) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    backfill = ShardBackfill(
        cluster=MagicMock(),
        shard_num=1,
        config=FlagEvaluationsBackfillConfig(max_unmerged_parts=0),
        instance=instance,
        run_id="backfill-run",
        log=MagicMock(),
        query_tags=DagsterTags(),
        workload=Workload.DEFAULT,
        node_role=NodeRole.ALL,
    )
    day = date(2026, 3, 10)

    with time_machine.travel(datetime(2026, 3, 12, tzinfo=UTC), tick=False) as clock:

        def create_blocking_run() -> None:
            # A minute on each side keeps the run's create_timestamp strictly between the clock
            # readings taken before and after it.
            clock.shift(timedelta(minutes=1))
            instance.create_run_for_job(job_def=deletes_job, status=dagster.DagsterRunStatus.STARTED)
            clock.shift(timedelta(minutes=1))

        def scan(*_args: Any, **_kwargs: Any) -> list[str]:
            if created_during == "wait_scan":
                create_blocking_run()
            return []

        def copy(*_args: Any) -> int:
            if created_during == "failed_copy":
                create_blocking_run()
                raise RuntimeError("insert failed partway")
            return 0

        with (
            patch("posthog.dags.flag_evaluations_backfill.describe_active_runs", side_effect=scan),
            patch.object(ShardBackfill, "check_disk_headroom"),
            patch.object(ShardBackfill, "check_consumer_lag"),
            patch.object(ShardBackfill, "copy_day", side_effect=copy),
            pytest.raises(dagster.Failure, match=f"started while {day} copied"),
        ):
            backfill.run([day])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides, kafka_path_row_age",
    [
        pytest.param({"min_free_bytes": 1 << 60}, timedelta(0), id="free_space_below_the_floor"),
        pytest.param(
            {"max_consumer_lag_seconds": 3600}, timedelta(hours=2), id="kafka_path_behind_by_more_than_the_limit"
        ),
        pytest.param({}, timedelta(days=2), id="kafka_path_silent_for_over_a_day"),
    ],
)
def test_backfill_fails_without_copying_when_a_safety_check_fails(
    cluster: ClickhouseCluster, overrides: dict[str, Any], kafka_path_row_age: timedelta
) -> None:
    now = datetime.now(UTC)
    seed_source_events(cluster, now, [INSIDE_RECENT])
    seed_flag_evaluation(cluster, now, replace(KAFKA_PATH_ROW, age=kafka_path_row_age))

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
    ],
)
def test_resolve_backfill_days_rejects_an_unsafe_window(overrides: dict[str, Any]) -> None:
    with pytest.raises(dagster.Failure):
        resolve_backfill_days(FlagEvaluationsBackfillConfig(**overrides), today=date(2026, 3, 10))
