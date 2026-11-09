import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from unittest.mock import patch

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags import geoip_backfill
from posthog.dags.geoip_backfill import (
    GeoipBackfillConfig,
    GeoipStagingTable,
    IngestionWindowConfig,
    geoip_backfill_staging_job,
)
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE

PUBLIC_IP = "216.160.83.56"
UNKNOWN_IP = "203.0.113.9"
RECORD = {"country": {"iso_code": "US", "names": {"en": "United States"}}}


class FakeLookup:
    build_epoch = 0

    def __call__(self, ip: str) -> dict[str, Any] | None:
        return RECORD if ip == PUBLIC_IP else None

    def close(self) -> None:
        pass


@frozen
class SeededEvent:
    label: str
    team_id: int
    properties: dict[str, Any]
    written_minutes_ago: int
    person_properties: dict[str, Any]
    event: str = "$pageview"

    @property
    def uuid(self) -> UUID:
        return uuid5(NAMESPACE_URL, self.label)


def seed(cluster: ClickhouseCluster, now: datetime, events: list[SeededEvent]) -> None:
    rows = [
        (
            event.uuid,
            event.event,
            json.dumps(event.properties, separators=(",", ":")),
            now - timedelta(minutes=event.written_minutes_ago),
            event.team_id,
            f"user-{event.label}",
            now,
            uuid4(),
            json.dumps(event.person_properties),
            now,
            "full",
            now - timedelta(minutes=event.written_minutes_ago),
        )
        for event in events
    ]
    cluster.any_host_by_role(
        Query(
            f"""INSERT INTO {EVENTS_DATA_TABLE()}
            (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id,
             person_properties, person_created_at, person_mode, _timestamp)
            VALUES""",
            rows,
        ),
        NodeRole.DATA,
    ).result()


def run_staging(
    cluster: ClickhouseCluster, now: datetime, tmp_path: Path, **overrides: Any
) -> dagster.ExecuteInProcessResult:
    mmdb = tmp_path / "GeoLite2-City.mmdb"
    mmdb.write_bytes(b"")
    config = GeoipBackfillConfig(
        windows=[
            IngestionWindowConfig(
                start=(now - timedelta(minutes=60)).isoformat(), end=(now - timedelta(minutes=10)).isoformat()
            )
        ],
        mmdb_path=str(mmdb),
        **overrides,
    )
    with patch.object(geoip_backfill, "open_lookup", return_value=FakeLookup()):
        return geoip_backfill_staging_job.execute_in_process(
            run_config=dagster.RunConfig(ops={"plan_geoip_backfill": config}),
            resources={"cluster": cluster},
            instance=dagster.DagsterInstance.ephemeral(),
        )


def staged_rows(cluster: ClickhouseCluster, table: GeoipStagingTable) -> dict[UUID, tuple[dict, dict, str]]:
    rows = cluster.any_host_by_role(
        Query(f"SELECT uuid, properties, person_properties, original_properties FROM {table.qualified_name} FINAL"),
        NodeRole.DATA,
    ).result()
    return {row[0]: (json.loads(row[1]), json.loads(row[2]), row[3]) for row in rows}


@pytest.mark.django_db
@pytest.mark.parametrize("max_rows_per_read", [1000, 1], ids=["one_read_per_slice", "slices_split"])
def test_staging_holds_enriched_copies_of_the_events_written_without_geoip(
    cluster: ClickhouseCluster, geoip_teams: tuple[int, int], tmp_path: Path, max_rows_per_read: int
) -> None:
    with_geoip, without_geoip = geoip_teams
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    damaged = SeededEvent(
        label="damaged",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP, "$set": {"email": "user@example.com"}},
        written_minutes_ago=30,
        person_properties={"email": "user@example.com", "$initial_geoip_country_code": "FR"},
    )
    second_damaged = SeededEvent(
        label="second_damaged",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP},
        written_minutes_ago=20,
        person_properties={},
    )
    already_enriched = SeededEvent(
        label="already_enriched",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP, "$geoip_country_code": "US", "$set": {"$geoip_country_code": "US"}},
        written_minutes_ago=30,
        person_properties={},
    )
    written_before_window = SeededEvent(
        label="written_before_window",
        team_id=with_geoip,
        properties={"$ip": PUBLIC_IP},
        written_minutes_ago=120,
        person_properties={},
    )
    unknown_address = SeededEvent(
        label="unknown_address",
        team_id=with_geoip,
        properties={"$ip": UNKNOWN_IP},
        written_minutes_ago=30,
        person_properties={},
    )
    team_without_geoip = SeededEvent(
        label="team_without_geoip",
        team_id=without_geoip,
        properties={"$ip": PUBLIC_IP},
        written_minutes_ago=30,
        person_properties={},
    )
    seed(
        cluster,
        now,
        [damaged, second_damaged, already_enriched, written_before_window, unknown_address, team_without_geoip],
    )
    result = run_staging(cluster, now, tmp_path, max_rows_per_read=max_rows_per_read)

    table = GeoipStagingTable(id=UUID(result.dagster_run.run_id))
    try:
        staged = staged_rows(cluster, table)
        assert set(staged) == {damaged.uuid, second_damaged.uuid}
        properties, person_properties, original_properties = staged[damaged.uuid]
        assert properties["$geoip_country_code"] == "US"
        assert properties["$set"]["email"] == "user@example.com"
        assert properties["$set"]["$geoip_country_code"] == "US"
        assert properties["$set"]["$geoip_city_name"] is None
        assert properties["$set_once"]["$initial_geoip_country_code"] == "US"
        assert person_properties["$geoip_country_code"] == "US"
        assert person_properties["$initial_geoip_country_code"] == "FR"
        assert json.loads(original_properties) == damaged.properties
        assert staged[second_damaged.uuid][1] == {}
    finally:
        cluster.map_hosts_by_role(table.drop, NodeRole.DATA).result()
