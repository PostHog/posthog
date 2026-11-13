import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.geoip_backfill import GeoipStagingTable
from posthog.dags.geoip_backfill_resend import GeoipResendConfig, geoip_backfill_resend_job, local_engine
from posthog.dags.tests.conftest import GeoipTeams
from posthog.dags.tests.test_geoip_backfill import PUBLIC_IP, SeededEvent, run_staging, seed
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.uuidt import uuid7

# The tables the MVs on sharded_events write. A resend must reach none of them.
MV_TARGETS = ("sharded_events_recent", "sharded_raw_sessions", "sharded_raw_sessions_v3")


def run_resend(
    cluster: ClickhouseCluster,
    staging_run_id: str,
    instance: dagster.DagsterInstance | None = None,
    **overrides: Any,
) -> dagster.ExecuteInProcessResult:
    return geoip_backfill_resend_job.execute_in_process(
        run_config=dagster.RunConfig(
            ops={"plan_geoip_resend": GeoipResendConfig(staging_run_id=staging_run_id, **overrides)}
        ),
        resources={"cluster": cluster},
        instance=instance or dagster.DagsterInstance.ephemeral(),
        raise_on_error=instance is None,
    )


def written(result: dagster.ExecuteInProcessResult) -> int:
    return sum(result.output_for_node("resend_shard").values())


def stored_rows(cluster: ClickhouseCluster, uuid: UUID, *, final: bool) -> list[tuple[dict, datetime]]:
    """The (properties, inserted_at) of each stored row of an event, the original before its copy."""
    rows = cluster.any_host_by_role(
        Query(
            f"SELECT properties, inserted_at FROM {EVENTS_DATA_TABLE()} {'FINAL' if final else ''} "
            "WHERE uuid = %(uuid)s ORDER BY _timestamp",
            {"uuid": uuid},
        ),
        NodeRole.DATA,
    ).result()
    return [(json.loads(properties), inserted_at) for properties, inserted_at in rows]


def mv_rows(cluster: ClickhouseCluster, team_id: int) -> dict[str, int]:
    return {
        table: cluster.any_host_by_role(
            Query(f"SELECT count() FROM {table} WHERE team_id = %(team_id)s", {"team_id": team_id}), NodeRole.DATA
        ).result()[0][0]
        for table in MV_TARGETS
    }


def drop_staging(cluster: ClickhouseCluster, run_id: str) -> None:
    cluster.map_hosts_by_role(GeoipStagingTable(id=UUID(run_id)).drop, NodeRole.DATA).result()


def damaged_event(label: str, team_id: int) -> SeededEvent:
    return SeededEvent(
        label=label,
        team_id=team_id,
        properties={"$ip": PUBLIC_IP, "$session_id": str(uuid7())},
        written_minutes_ago=30,
        person_properties={},
    )


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True], ids=["resend", "dry_run"])
def test_resend_attaches_the_copies_and_deletes_their_originals(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path, dry_run: bool
) -> None:
    with_geoip = geoip_teams.with_geoip
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    damaged = damaged_event(f"resend_damaged_{dry_run}", with_geoip)
    deleted_after_staging = damaged_event(f"resend_deleted_{dry_run}", with_geoip)
    seed(cluster, now, [damaged, deleted_after_staging])
    [(_, original_inserted_at)] = stored_rows(cluster, damaged.uuid, final=False)
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    try:
        cluster.map_hosts_by_role(
            Query(
                f"DELETE FROM {EVENTS_DATA_TABLE()} WHERE uuid = %(uuid)s",
                {"uuid": deleted_after_staging.uuid},
            ),
            NodeRole.DATA,
        ).result()
        before = mv_rows(cluster, with_geoip)

        first = run_resend(cluster, staging_run_id, dry_run=dry_run)
        second = run_resend(cluster, staging_run_id, dry_run=dry_run)

        assert stored_rows(cluster, deleted_after_staging.uuid, final=False) == []
        assert mv_rows(cluster, with_geoip) == before
        if dry_run:
            assert [written(first), written(second)] == [1, 1]
            assert stored_rows(cluster, damaged.uuid, final=False) == [(damaged.properties, original_inserted_at)]
        else:
            assert [written(first), written(second)] == [1, 0]
            # The original is gone without a merge, and the copy keeps its insert time.
            [(properties, inserted_at)] = stored_rows(cluster, damaged.uuid, final=False)
            assert properties["$geoip_country_code"] == "US"
            assert inserted_at == original_inserted_at
    finally:
        drop_staging(cluster, staging_run_id)


@pytest.mark.django_db
def test_resend_skips_an_event_whose_copy_is_in_already(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    damaged = damaged_event("resend_copy_in_already", geoip_teams.with_geoip)
    seed(cluster, now, [damaged])
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    table = GeoipStagingTable(id=UUID(staging_run_id))
    try:
        # A run that attached the copy and stopped before the delete leaves both rows.
        columns = ", ".join(column.quoted for column in cluster.any_host_by_role(table.columns, NodeRole.DATA).result())
        cluster.any_host_by_role(
            Query(f"INSERT INTO {EVENTS_DATA_TABLE()} ({columns}) SELECT {columns} FROM {table.qualified_name}"),
            NodeRole.DATA,
        ).result()

        assert written(run_resend(cluster, staging_run_id, dry_run=True)) == 0
    finally:
        drop_staging(cluster, staging_run_id)


@pytest.mark.django_db
def test_resend_refuses_to_start_while_another_resend_executes(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    damaged = damaged_event("resend_other_run", geoip_teams.with_geoip)
    seed(cluster, now, [damaged])
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    instance = dagster.DagsterInstance.ephemeral()
    instance.create_run_for_job(
        job_def=geoip_backfill_resend_job,
        status=dagster.DagsterRunStatus.STARTED,
        run_config={"ops": {"plan_geoip_resend": {"config": {"staging_run_id": staging_run_id}}}},
    )
    try:
        result = run_resend(cluster, staging_run_id, instance, dry_run=False)

        assert not result.success
        [failure] = [event for event in result.all_events if event.is_step_failure]
        assert "is executing" in str(failure.step_failure_data.error)
        [(properties, _)] = stored_rows(cluster, damaged.uuid, final=False)
        assert properties == damaged.properties
    finally:
        drop_staging(cluster, staging_run_id)


@pytest.mark.parametrize(
    "engine_full, expected",
    [
        pytest.param(
            "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.events', '{replica}', _timestamp) "
            "PARTITION BY toYYYYMM(timestamp) ORDER BY (team_id, uuid) SETTINGS index_granularity = 8192",
            "ReplacingMergeTree(_timestamp) PARTITION BY toYYYYMM(timestamp) ORDER BY (team_id, uuid) "
            "SETTINGS index_granularity = 8192",
            id="replacing",
        ),
        pytest.param(
            "ReplicatedMergeTree('/clickhouse/tables/{shard}/t', '{replica}') ORDER BY id",
            "MergeTree() ORDER BY id",
            id="no_engine_arguments",
        ),
        pytest.param(
            "ReplacingMergeTree(_timestamp) ORDER BY id", "ReplacingMergeTree(_timestamp) ORDER BY id", id="local"
        ),
    ],
)
def test_local_engine(engine_full: str, expected: str) -> None:
    assert local_engine(engine_full) == expected
