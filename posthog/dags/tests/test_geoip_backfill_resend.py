import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.geoip_backfill import GeoipStagingTable
from posthog.dags.geoip_backfill_resend import GeoipResendConfig, geoip_backfill_resend_job
from posthog.dags.tests.conftest import GeoipTeams
from posthog.dags.tests.test_geoip_backfill import PUBLIC_IP, SeededEvent, run_staging, seed
from posthog.models.ai_events.sql import DATA_TABLE_NAME as AI_EVENTS_DATA_TABLE
from posthog.models.event.sql import EVENTS_DATA_TABLE


def run_resend(cluster: ClickhouseCluster, staging_run_id: str, **overrides: Any) -> dagster.ExecuteInProcessResult:
    return geoip_backfill_resend_job.execute_in_process(
        run_config=dagster.RunConfig(
            ops={"plan_geoip_resend": GeoipResendConfig(staging_run_id=staging_run_id, **overrides)}
        ),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
    )


def written(result: dagster.ExecuteInProcessResult) -> int:
    return sum(result.output_for_node("resend_shard").values())


def stored_properties(cluster: ClickhouseCluster, table: str, uuid: UUID, *, final: bool) -> list[dict]:
    rows = cluster.any_host_by_role(
        Query(
            f"SELECT DISTINCT properties FROM {table} {'FINAL' if final else ''} WHERE uuid = %(uuid)s",
            {"uuid": uuid},
        ),
        NodeRole.DATA,
    ).result()
    return sorted((json.loads(properties) for (properties,) in rows), key=len)


def seed_ai_event(cluster: ClickhouseCluster, now: datetime, event: SeededEvent, properties: dict[str, Any]) -> None:
    timestamp = now - timedelta(minutes=event.written_minutes_ago)
    cluster.any_host_by_role(
        Query(
            f"""INSERT INTO {AI_EVENTS_DATA_TABLE}
            (uuid, event, timestamp, team_id, distinct_id, person_id, properties, trace_id, is_error,
             retention_days, _timestamp, _offset, _partition)
            VALUES""",
            [
                (
                    event.uuid,
                    event.event,
                    timestamp,
                    event.team_id,
                    f"user-{event.label}",
                    UUID(int=0),
                    json.dumps(properties, separators=(",", ":")),
                    "trace",
                    0,
                    10000,
                    timestamp,
                    0,
                    0,
                )
            ],
        ),
        NodeRole.DATA,
    ).result()


def drop_staging(cluster: ClickhouseCluster, run_id: str) -> None:
    cluster.map_hosts_by_role(GeoipStagingTable(id=UUID(run_id)).drop, NodeRole.DATA).result()


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True], ids=["resend", "dry_run"])
def test_resend_writes_staged_rows_whose_original_is_unchanged(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path, dry_run: bool
) -> None:
    with_geoip = geoip_teams.with_geoip
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    damaged = SeededEvent(
        label=f"resend_damaged_{dry_run}",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP},
        written_minutes_ago=30,
        person_properties={},
    )
    deleted_after_staging = SeededEvent(
        label=f"resend_deleted_{dry_run}",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP},
        written_minutes_ago=30,
        person_properties={},
    )
    seed(cluster, now, [damaged, deleted_after_staging])
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    try:
        cluster.map_hosts_by_role(
            Query(
                f"DELETE FROM {EVENTS_DATA_TABLE()} WHERE uuid = %(uuid)s",
                {"uuid": deleted_after_staging.uuid},
            ),
            NodeRole.DATA,
        ).result()

        first = run_resend(cluster, staging_run_id, dry_run=dry_run)
        second = run_resend(cluster, staging_run_id, dry_run=dry_run)

        assert stored_properties(cluster, EVENTS_DATA_TABLE(), deleted_after_staging.uuid, final=False) == []
        # Until a merge collapses the original with its staged copy, the second run finds the original
        # again and writes the same staged row, which collapses too.
        assert [written(first), written(second)] == [1, 1]
        [final] = stored_properties(cluster, EVENTS_DATA_TABLE(), damaged.uuid, final=True)
        if dry_run:
            assert final == damaged.properties
        else:
            assert final["$geoip_country_code"] == "US"
            assert stored_properties(cluster, EVENTS_DATA_TABLE(), damaged.uuid, final=False)[0] == damaged.properties
    finally:
        drop_staging(cluster, staging_run_id)


@pytest.mark.django_db
def test_resend_rewrites_ai_events_whose_properties_are_unchanged(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    with_geoip = geoip_teams.with_geoip
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    generation = SeededEvent(
        label="ai_generation",
        team_id=with_geoip,
        event="$ai_generation",
        properties={"$ip": PUBLIC_IP, "$ai_trace_id": "trace", "$ai_input": "large prompt"},
        written_minutes_ago=30,
        person_properties={},
    )
    rewritten_since = SeededEvent(
        label="ai_rewritten_since",
        team_id=with_geoip,
        event="$ai_generation",
        properties={"$ip": PUBLIC_IP, "$ai_trace_id": "trace"},
        written_minutes_ago=30,
        person_properties={},
    )
    seed(cluster, now, [generation, rewritten_since])
    seed_ai_event(cluster, now, generation, {"$ip": PUBLIC_IP, "$ai_trace_id": "trace"})
    seed_ai_event(cluster, now, rewritten_since, {"$ai_trace_id": "trace"})
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    try:
        run_resend(cluster, staging_run_id, dry_run=False, include_ai_events=True)

        [repaired] = stored_properties(cluster, AI_EVENTS_DATA_TABLE, generation.uuid, final=False)
        assert repaired["$geoip_country_code"] == "US"
        assert repaired["$set"]["$geoip_country_code"] == "US"
        assert "$ai_input" not in repaired
        assert stored_properties(cluster, AI_EVENTS_DATA_TABLE, rewritten_since.uuid, final=False) == [
            {"$ai_trace_id": "trace"}
        ]
    finally:
        drop_staging(cluster, staging_run_id)
