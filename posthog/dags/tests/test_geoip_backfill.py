import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

import brotli
import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.geoip_backfill import (
    Exclusion,
    GeoipBackfillConfig,
    GeoipStagingTable,
    IngestionWindow,
    IngestionWindowConfig,
    StagingRunConfig,
    TeamDecision,
    cleanup_geoip_backfill_staging,
    decide_team,
    enriched_person_properties,
    geoip_backfill_staging_job,
    node_json,
    plan_windows,
)
from posthog.dags.geoip_enrichment import TEMPLATE_VERSIONS, geoip_enrichment
from posthog.dags.tests.conftest import GeoipTeams, geoip_template_source
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.dmat_slot_assignments.sql import DMAT_SLOT_ASSIGNMENTS_TABLE_NAME
from posthog.models.event.sql import EVENTS_DATA_TABLE

from products.cdp.backend.facade.api import EnabledTransformation
from products.cdp.backend.models.hog_functions import HogFunction

# Addresses in the MaxMind test DB, which the staging job reads through the real reader.
TEST_MMDB = Path(__file__).parent / "fixtures" / "GeoLite2-City-Test.mmdb.br"
PUBLIC_IP = "216.160.83.56"
UNKNOWN_IP = "203.0.113.9"
RECORD = {"country": {"iso_code": "US", "names": {"en": "United States"}}}


def fake_lookup(ip: str) -> dict[str, Any] | None:
    return RECORD if ip == PUBLIC_IP else None


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
    mmdb = tmp_path / "GeoLite2-City-Test.mmdb"
    mmdb.write_bytes(brotli.decompress(TEST_MMDB.read_bytes()))
    config = GeoipBackfillConfig(
        windows=[
            IngestionWindowConfig(
                start=(now - timedelta(minutes=60)).isoformat(), end=(now - timedelta(minutes=10)).isoformat()
            )
        ],
        mmdb_path=str(mmdb),
        **overrides,
    )
    return geoip_backfill_staging_job.execute_in_process(
        run_config=dagster.RunConfig(ops={"plan_geoip_backfill": config}),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
    )


@frozen
class StagedRow:
    properties: dict[str, Any]
    person_properties: dict[str, Any]
    original_properties: str


def staged_rows(cluster: ClickhouseCluster, table: GeoipStagingTable) -> dict[UUID, StagedRow]:
    rows = cluster.any_host_by_role(
        Query(f"SELECT uuid, properties, person_properties, original_properties FROM {table.qualified_name} FINAL"),
        NodeRole.DATA,
    ).result()
    return {
        row[0]: StagedRow(
            properties=json.loads(row[1]), person_properties=json.loads(row[2]), original_properties=row[3]
        )
        for row in rows
    }


def row_by_uuid(cluster: ClickhouseCluster, table: str, uuid: UUID, columns: list[str]) -> dict[str, Any]:
    [row] = cluster.any_host_by_role(
        Query(
            f"SELECT {', '.join(f'`{name}`' for name in columns)} FROM {table} FINAL WHERE uuid = %(uuid)s",
            {"uuid": uuid},
        ),
        NodeRole.DATA,
    ).result()
    return dict(zip(columns, row))


def run_cleanup(cluster: ClickhouseCluster, table: GeoipStagingTable) -> None:
    cleanup_geoip_backfill_staging.execute_in_process(
        run_config=dagster.RunConfig(ops={"drop_staging_table": StagingRunConfig(staging_run_id=str(table.id))}),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
    )


# Each case is a property text and what `JSON.stringify(JSON.parse(text))` returns for it in Node.
NODE_JSON_CASES = [
    pytest.param(
        '{"title":"caf\\ud83d","low":"\\udc00x","pair":"\\ud83d\\ude00","e":"é","emoji":"😀","ctrl":"\\u0001\\n\\t\\u001f","del":"\\u007f","u2028":"\\u2028","slash":"a\\/b","quote":"\\"","backslash":"\\\\"}',
        '{"title":"caf\\ud83d","low":"\\udc00x","pair":"😀","e":"é","emoji":"😀","ctrl":"\\u0001\\n\\t\\u001f","del":"\x7f","u2028":"\u2028","slash":"a/b","quote":"\\"","backslash":"\\\\"}',
        id="strings",
    ),
    pytest.param(
        '{"small":0.00001,"tiny":1e-7,"edge":0.000001,"big":1e21,"under":1e20,"bigint":12345678901234567000,"whole":13.0,"neg":-0.5,"zero":-0,"sci":1.5e300,"mid":123456789012345680000,"pi":3.141592653589793,"third":0.3333333333333333,"exp":2e-310,"list":[1.0,2.5,null,true,false,{},[]]}',
        '{"small":0.00001,"tiny":1e-7,"edge":0.000001,"big":1e+21,"under":100000000000000000000,"bigint":12345678901234567000,"whole":13,"neg":-0.5,"zero":0,"sci":1.5e+300,"mid":123456789012345680000,"pi":3.141592653589793,"third":0.3333333333333333,"exp":2e-310,"list":[1,2.5,null,true,false,{},[]]}',
        id="numbers",
    ),
    pytest.param(
        '{"nested":{"a":[{"b":1.10},{"c":"\\ud800"}]},"key\\ud83d":1}',
        '{"nested":{"a":[{"b":1.1},{"c":"\\ud800"}]},"key\\ud83d":1}',
        id="nested",
    ),
]


@pytest.mark.parametrize("text, node_text", NODE_JSON_CASES)
def test_node_json_writes_what_json_stringify_writes(text: str, node_text: str) -> None:
    assert node_json(json.loads(text)) == node_text


WINDOWS_NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
CURRENT_VERSION = TEMPLATE_VERSIONS[-1]


def transformation(template_id: str, *, hog: str = "return event", has_filters: bool = False) -> EnabledTransformation:
    return EnabledTransformation(team_id=1, template_id=template_id, hog=hog, has_filters=has_filters)


def geoip(*, hog: str | None = None, has_filters: bool = False) -> EnabledTransformation:
    return transformation("template-geoip", hog=hog or geoip_template_source(), has_filters=has_filters)


@pytest.mark.parametrize(
    "transformations, reviewed, expected",
    [
        pytest.param([geoip()], False, TeamDecision(version=CURRENT_VERSION), id="repairable"),
        pytest.param(
            [geoip(hog=f"\n{geoip_template_source()}\n")],
            False,
            TeamDecision(version=CURRENT_VERSION),
            id="source_saved_with_whitespace",
        ),
        pytest.param(
            [transformation("template-other"), geoip()],
            False,
            TeamDecision(version=CURRENT_VERSION),
            id="earlier_transformation",
        ),
        pytest.param([geoip(has_filters=True)], False, TeamDecision(exclusion=Exclusion.FILTERS), id="filters"),
        pytest.param([geoip(hog="return event")], False, TeamDecision(exclusion=Exclusion.EDITED_SOURCE), id="edited"),
        pytest.param(
            [geoip(), transformation("template-other")],
            False,
            TeamDecision(exclusion=Exclusion.LATER_TRANSFORMATION),
            id="later_transformation",
        ),
        pytest.param(
            [transformation("plugin-posthog-plugin-geoip")],
            False,
            TeamDecision(exclusion=Exclusion.LEGACY_GEOIP_PLUGIN),
            id="legacy_plugin",
        ),
        pytest.param(
            [transformation("template-other")], False, TeamDecision(exclusion=Exclusion.NO_GEOIP), id="no_geoip"
        ),
        pytest.param(
            [geoip(hog="return event", has_filters=True), transformation("template-other")],
            True,
            TeamDecision(version=CURRENT_VERSION),
            id="reviewed",
        ),
    ],
)
def test_decide_team(transformations: list[EnabledTransformation], reviewed: bool, expected: TeamDecision) -> None:
    assert decide_team(transformations, reviewed=reviewed) == expected


@pytest.mark.parametrize(
    "windows, expected",
    [
        pytest.param(
            [("2026-01-10T08:00:00", "2026-01-10T09:00:00")],
            [(datetime(2026, 1, 10, 8, tzinfo=UTC), datetime(2026, 1, 10, 9, tzinfo=UTC))],
            id="naive_times_are_utc",
        ),
        pytest.param(
            [("2026-01-10T10:00:00.250+02:00", "2026-01-10T11:00:00.750+02:00")],
            [(datetime(2026, 1, 10, 8, tzinfo=UTC), datetime(2026, 1, 10, 9, tzinfo=UTC))],
            id="offset_converted_and_fraction_dropped",
        ),
        pytest.param(
            [("2026-01-10T10:00:00", "2026-01-10T11:00:00"), ("2026-01-09T10:00:00", "2026-01-09T11:00:00")],
            [
                (datetime(2026, 1, 9, 10, tzinfo=UTC), datetime(2026, 1, 9, 11, tzinfo=UTC)),
                (datetime(2026, 1, 10, 10, tzinfo=UTC), datetime(2026, 1, 10, 11, tzinfo=UTC)),
            ],
            id="sorted_by_start",
        ),
    ],
)
def test_plan_windows_reads_windows_as_utc(
    windows: list[tuple[str, str]], expected: list[tuple[datetime, datetime]]
) -> None:
    config = GeoipBackfillConfig(windows=[IngestionWindowConfig(start=start, end=end) for start, end in windows])

    planned = plan_windows(config, WINDOWS_NOW)

    assert [(window.start, window.end) for window in planned] == expected


@pytest.mark.parametrize(
    "windows",
    [
        pytest.param([], id="no_window"),
        pytest.param([("2026-01-10T09:00:00", "2026-01-10T09:00:00")], id="empty_window"),
        pytest.param([("2026-01-10T09:00:00", "2026-01-10T08:00:00")], id="backwards"),
        pytest.param([("2026-01-10T11:00:00", "2026-01-10T13:00:00")], id="ends_in_the_future"),
    ],
)
def test_plan_windows_rejects_windows_it_cannot_read(windows: list[tuple[str, str]]) -> None:
    config = GeoipBackfillConfig(windows=[IngestionWindowConfig(start=start, end=end) for start, end in windows])

    with pytest.raises(dagster.Failure):
        plan_windows(config, WINDOWS_NOW)


def test_window_slices_and_halves_cover_the_window_without_gaps() -> None:
    start = datetime(2026, 1, 10, 8, tzinfo=UTC)
    window = IngestionWindow(start=start, end=start + timedelta(minutes=12, seconds=7))

    slices = list(window.slices(5))
    halves = IngestionWindow(start=start, end=start + timedelta(seconds=3)).halves()

    assert [(piece.start, piece.end) for piece in slices] == [
        (start, start + timedelta(minutes=5)),
        (start + timedelta(minutes=5), start + timedelta(minutes=10)),
        (start + timedelta(minutes=10), window.end),
    ]
    assert [(half.start, half.end) for half in halves] == [
        (start, start + timedelta(seconds=1)),
        (start + timedelta(seconds=1), start + timedelta(seconds=3)),
    ]
    assert not IngestionWindow(start=start, end=start + timedelta(seconds=1)).can_split


@pytest.mark.parametrize(
    "person_mode, person_properties, expected",
    [
        pytest.param(
            "full",
            {"email": "user@example.com", "$geoip_country_code": "FR", "$initial_geoip_country_code": "FR"},
            {
                "email": "user@example.com",
                "$geoip_country_code": "US",
                "$geoip_country_name": "United States",
                "$initial_geoip_country_code": "FR",
                "$initial_geoip_country_name": "United States",
            },
            id="set_overwrites_and_set_once_keeps",
        ),
        pytest.param("propertyless", {"email": "user@example.com"}, {"email": "user@example.com"}, id="personless"),
        pytest.param("full", {}, {}, id="no_person_properties"),
    ],
)
def test_enriched_person_properties(
    person_mode: str, person_properties: dict[str, Any], expected: dict[str, Any]
) -> None:
    enrichment = geoip_enrichment({"$ip": PUBLIC_IP}, fake_lookup, CURRENT_VERSION)
    assert enrichment is not None
    row = {"person_mode": person_mode, "person_properties": json.dumps(person_properties)}

    enriched = enriched_person_properties(row, enrichment)

    assert {key: value for key, value in enriched.items() if value is not None} == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "max_rows_per_read, only_team_without_geoip",
    [(1000, False), (1, False), (1000, True)],
    ids=["one_read_per_slice", "slices_split", "other_team_only"],
)
def test_staging_holds_enriched_copies_of_the_events_written_without_geoip(
    cluster: ClickhouseCluster,
    geoip_teams: GeoipTeams,
    tmp_path: Path,
    max_rows_per_read: int,
    only_team_without_geoip: bool,
) -> None:
    with_geoip = geoip_teams.with_geoip
    without_geoip = geoip_teams.without_geoip
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
    result = run_staging(
        cluster,
        now,
        tmp_path,
        max_rows_per_read=max_rows_per_read,
        team_ids=[without_geoip] if only_team_without_geoip else None,
    )

    table = GeoipStagingTable(id=UUID(result.dagster_run.run_id))
    try:
        staged = staged_rows(cluster, table)
        if only_team_without_geoip:
            assert staged == {}
        else:
            assert_damaged_events_staged(cluster, table, staged, damaged, second_damaged)
    finally:
        run_cleanup(cluster, table)
    assert not cluster.any_host_by_role(table.exists, NodeRole.DATA).result()


def assert_damaged_events_staged(
    cluster: ClickhouseCluster,
    table: GeoipStagingTable,
    staged: dict[UUID, StagedRow],
    damaged: SeededEvent,
    second_damaged: SeededEvent,
) -> None:
    assert set(staged) == {damaged.uuid, second_damaged.uuid}
    columns = [column.name for column in cluster.any_host_by_role(table.columns, NodeRole.DATA).result()]
    original = row_by_uuid(cluster, EVENTS_DATA_TABLE(), damaged.uuid, columns)
    copy = row_by_uuid(cluster, table.qualified_name, damaged.uuid, columns)
    assert "inserted_at" in columns
    assert {name for name in columns if original[name] != copy[name]} == {
        "properties",
        "person_properties",
        "_timestamp",
    }
    assert copy["_timestamp"] > original["_timestamp"]
    row = staged[damaged.uuid]
    assert row.properties["$geoip_country_code"] == "US"
    assert row.properties["$set"]["email"] == "user@example.com"
    assert row.properties["$set"]["$geoip_country_code"] == "US"
    assert row.properties["$set"]["$geoip_city_name"] == "Milton"
    assert row.properties["$set"]["$geoip_subdivision_2_name"] is None
    assert row.properties["$set_once"]["$initial_geoip_country_code"] == "US"
    assert row.person_properties["$geoip_country_code"] == "US"
    assert row.person_properties["$initial_geoip_country_code"] == "FR"
    assert json.loads(row.original_properties) == damaged.properties
    assert staged[second_damaged.uuid].person_properties == {}


def output_metadata(result: dagster.ExecuteInProcessResult, node: str) -> dict[str, Any]:
    [output] = [event for event in result.events_for_node(node) if event.event_type_value == "STEP_OUTPUT"]
    return {key: value.value for key, value in output.step_output_data.metadata.items()}


@pytest.mark.django_db
def test_staging_leaves_out_and_reports_the_teams_it_cannot_repair(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    organization = Team.objects.get(id=geoip_teams.with_geoip).organization

    def team_with(template_id: str, hog: str, *, filters: dict | None = None, anonymize_ips: bool = False) -> int:
        team = Team.objects.create(organization=organization, anonymize_ips=anonymize_ips)
        HogFunction.objects.create(
            team=team, type="transformation", template_id=template_id, enabled=True, hog=hog, filters=filters
        )
        return team.id

    source = geoip_template_source()
    filtered = team_with("template-geoip", source, filters={"events": [{"id": "$pageview", "type": "events"}]})
    legacy_plugin = team_with("plugin-posthog-plugin-geoip", "return event")
    materialized = team_with("template-geoip", source)
    anonymized = team_with("template-geoip", source, anonymize_ips=True)
    reviewed = team_with("template-geoip", "return event")
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    events = {
        team_id: SeededEvent(
            label=f"left-out-{team_id}",
            team_id=team_id,
            properties={} if team_id == anonymized else {"$ip": PUBLIC_IP},
            written_minutes_ago=30,
            person_properties={},
        )
        for team_id in (
            geoip_teams.with_geoip,
            geoip_teams.without_geoip,
            filtered,
            legacy_plugin,
            materialized,
            anonymized,
            reviewed,
        )
    }
    seed(cluster, now, list(events.values()))
    cluster.any_host_by_role(
        Query(
            f"INSERT INTO {DMAT_SLOT_ASSIGNMENTS_TABLE_NAME} (team_id, column_index, property_name) VALUES",
            [(materialized, 0, "$geoip_country_code")],
        ),
        NodeRole.DATA,
    ).result()
    try:
        result = run_staging(cluster, now, tmp_path, reviewed_team_ids=[reviewed])
    finally:
        cluster.any_host_by_role(
            Query(
                f"DELETE FROM {DMAT_SLOT_ASSIGNMENTS_TABLE_NAME} WHERE team_id = %(team_id)s", {"team_id": materialized}
            ),
            NodeRole.DATA,
        ).result()

    table = GeoipStagingTable(id=UUID(result.dagster_run.run_id))
    try:
        staged = staged_rows(cluster, table)
    finally:
        run_cleanup(cluster, table)
    assert set(staged) == {events[geoip_teams.with_geoip].uuid, events[reviewed].uuid}
    metadata = output_metadata(result, "find_affected_teams")
    assert {key: value for key, value in metadata.items() if key.endswith("_team_ids") and value} == {
        "filters_team_ids": [filtered],
        "legacy_geoip_plugin_team_ids": [legacy_plugin],
        "materialized_geoip_team_ids": [materialized],
    }
    assert metadata["no_geoip_events"] == 1
    assert metadata["anonymize_ips_teams"] == 1
    assert metadata["anonymize_ips_events"] == 1
