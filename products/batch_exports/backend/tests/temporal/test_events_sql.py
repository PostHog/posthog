import json
import uuid
import datetime as dt

import pytest

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import TEMPORARY_PROPERTIES_JSON_TYPE
from posthog.models.event.sql import EVENTS_JSON_CLEANER, EVENTS_PROPERTIES_JSON_TYPE
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.events import generate_test_events, insert_event_values_in_clickhouse

from products.batch_exports.backend.service import BatchExportField
from products.batch_exports.backend.temporal.destinations.http_batch_export import http_default_fields
from products.batch_exports.backend.temporal.filters import compose_filters_clause
from products.batch_exports.backend.temporal.sql.events import (
    _NATIVE_EVENTS_FIELD_EXPRESSIONS,
    native_events_export_query,
    native_recent_events_export_query,
)

QUERY_PARAMETERS: dict[str, object] = {
    "team_id": 1,
    "interval_start": None,
    "interval_end": "2026-01-01 00:00:00",
    "include_events": [],
    "exclude_events": [],
}


def test_native_events_export_query_refuses_stale_replicas() -> None:
    query = native_events_export_query([{"expression": "event", "alias": "event"}])

    assert "max_replica_delay_for_distributed_queries=60" in query
    assert "fallback_to_stale_replicas_for_distributed_queries=0" in query


def test_native_events_export_query_keeps_empty_object_literals_in_custom_fields() -> None:
    query = ClickHouseClient().prepare_query(
        native_events_export_query([{"expression": "'{}'", "alias": "properties"}]), QUERY_PARAMETERS
    )

    assert "'{0}'" not in query
    assert "'{}'" in query


# Without these settings `toJSONString(properties)` prints a stored dotted key as `a%2Eb` and a `/` as `\/`.
@pytest.mark.parametrize("setting", ["json_type_escape_dots_in_keys=1", "output_format_json_escape_forward_slashes=0"])
def test_native_events_export_query_matches_legacy_json_text(setting: str) -> None:
    assert setting in native_events_export_query([{"expression": "event", "alias": "event"}])


@pytest.mark.parametrize(
    "sent_properties,expected,expected_set",
    [
        (
            {"cart": {"items": 2, "note": None}, "tags": ["a"]},
            {"cart": {"items": 2, "note": None}, "tags": ["a"]},
            None,
        ),
        (
            {"$browser": "Firefox", "$feature/checkout": True},
            {"$browser": "Firefox", "$feature_flags": {"checkout": "true"}},
            None,
        ),
        (
            {"plan": "pro", "$set": {"email": "a@example.com"}},
            {"plan": "pro", "$set": {"email": "a@example.com"}},
            {"email": "a@example.com"},
        ),
    ],
    ids=["no-flags-or-built-in-properties", "flags-and-built-in-properties", "temporary-properties"],
)
@pytest.mark.django_db
def test_native_events_export_sends_properties_without_storage_defaults(
    sent_properties: dict[str, object], expected: dict[str, object], expected_set: dict[str, object] | None
) -> None:
    """The exported document puts back what the ingestion cleaner stores as text, and leaves out its defaults."""
    result = sync_execute(
        f"SELECT {_NATIVE_EVENTS_FIELD_EXPRESSIONS['properties']}, {_NATIVE_EVENTS_FIELD_EXPRESSIONS['set']} FROM ("
        f"SELECT CAST(cleaned.properties, '{EVENTS_PROPERTIES_JSON_TYPE()}') AS properties, "
        f"CAST(cleaned.temporary_properties, '{TEMPORARY_PROPERTIES_JSON_TYPE}') AS temporary_properties "
        f"FROM (SELECT {EVENTS_JSON_CLEANER}(%(properties)s, '{{}}') AS cleaned)"
        ") AS events",
        {"properties": json.dumps(sent_properties)},
    )

    [(properties, set_field)] = result
    assert json.loads(properties) == expected
    assert (json.loads(set_field) if set_field is not None else None) == expected_set


_STORED_RECENT_EVENTS = {
    "with-flag": (
        '{"$browser":"Chrome","$feature_flags":{"checkout":"true"},"page":"/a/b",'
        '"$set":{"email":"a@example.com"},"$set_once":{"plan":"free"}}',
        '{"$set":{"email":"a@example.com"},"$set_once":{"plan":"free"}}',
    ),
    "without-flag": ('{"$browser":"Firefox","$os":"Mac OS X"}', "{}"),
    "$feature_flag_called": ('{"$feature_flag":"checkout","$feature_flag_response":"true"}', "{}"),
}


def _export_recent_events(
    team_id: int, fields: list, *, includes_feature_flag_called: bool, reads_typed_columns: bool
) -> list[tuple]:
    now = dt.datetime.now(tz=dt.UTC)
    sync_execute(
        """
        INSERT INTO sharded_events_json_recent
            (uuid, event, properties, person_properties, temporary_properties, team_id, distinct_id, timestamp, inserted_at)
        VALUES
        """,
        [
            (uuid.uuid4(), event, properties, '{"email":"a@example.com"}', temporary, team_id, "d1", now, now)
            for event, (properties, temporary) in _STORED_RECENT_EVENTS.items()
        ],
    )
    query = native_recent_events_export_query(
        fields,
        includes_feature_flag_called=includes_feature_flag_called,
        reads_typed_columns=reads_typed_columns,
    ).replace("FORMAT ArrowStream", "")
    return sync_execute(
        query,
        {
            "team_id": team_id,
            "interval_start": now - dt.timedelta(hours=1),
            "interval_end": now + dt.timedelta(hours=1),
            "include_events": [],
            "exclude_events": [],
        },
    )


@pytest.mark.parametrize("reads_typed_columns", [False, True], ids=["plain-read", "typed-read"])
@pytest.mark.parametrize(
    "includes_feature_flag_called,expected_events",
    [
        (False, {"with-flag", "without-flag"}),
        (True, {"with-flag", "without-flag", "$feature_flag_called"}),
    ],
    ids=["feature-flag-called-left-out", "feature-flag-called-allowed"],
)
@pytest.mark.django_db
def test_native_recent_events_export_sends_stored_documents(
    team, includes_feature_flag_called: bool, expected_events: set[str], reads_typed_columns: bool
) -> None:
    rows = _export_recent_events(
        team.pk,
        [
            {"expression": "event", "alias": "event"},
            {"expression": "properties", "alias": "properties"},
            {"expression": "person_properties", "alias": "person_properties"},
            {"expression": "set", "alias": "set"},
            {"expression": "set_once", "alias": "set_once"},
        ],
        includes_feature_flag_called=includes_feature_flag_called,
        reads_typed_columns=reads_typed_columns,
    )

    assert {row[0] for row in rows} == expected_events
    for event, properties, person_properties, set_field, set_once_field in rows:
        assert properties == _STORED_RECENT_EVENTS[event][0]
        assert person_properties == '{"email":"a@example.com"}'
        expected_set_fields = ('{"email":"a@example.com"}', '{"plan":"free"}') if event == "with-flag" else (None, None)
        assert (set_field, set_once_field) == expected_set_fields


@pytest.mark.django_db
def test_native_recent_events_export_rebuilds_whole_documents_without_repeating_temporary_properties(team) -> None:
    fields = http_default_fields(reads_native_events=True)
    rows = _export_recent_events(team.pk, fields, includes_feature_flag_called=False, reads_typed_columns=True)

    aliases = [field["alias"] for field in fields]
    properties_by_event = {row[aliases.index("event")]: row[aliases.index("properties")] for row in rows}
    members = json.loads(properties_by_event["with-flag"], object_pairs_hook=lambda pairs: pairs)
    assert [key for key, _ in members].count("$set") == 1


_SENT_EVENTS: dict[str, tuple[dict, dict]] = {
    "nested": (
        {"cart": {"plan": "pro"}, "tags": ["a"], "$feature/checkout": True, "$set": {"email": "a@example.com"}},
        {"org": {"tier": "gold"}},
    ),
    "flat": ({"cart": "pro", "$os": "Mac OS X"}, {"org": "gold"}),
}


async def _read_native_exports(
    clickhouse_client, team_id: int, sent_events: dict[str, tuple[dict, dict]], fields: list, filters: list[dict]
) -> dict[str, list[dict]]:
    now = dt.datetime.now(tz=dt.UTC)
    await insert_event_values_in_clickhouse(
        clickhouse_client,
        [
            sent_event
            for event, (properties, person_properties) in sent_events.items()
            for sent_event in generate_test_events(
                count=1,
                team_id=team_id,
                possible_datetimes=[now],
                event_name=event,
                inserted_at=now,
                properties=properties,
                person_properties=person_properties,
            )
        ],
    )
    filters_str, filter_values = (
        await database_sync_to_async(compose_filters_clause)(filters, team_id=team_id, use_new_events_schema=True)
        if filters
        else ("", {})
    )
    parameters = {
        **filter_values,
        "team_id": team_id,
        "interval_start": (now - dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "interval_end": (now + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "include_events": [],
        "exclude_events": [],
    }

    rows_by_table = {}
    for table, query in (
        ("events_json", native_events_export_query(fields, filters_str)),
        (
            "events_json_recent",
            native_recent_events_export_query(
                fields, filters_str, includes_feature_flag_called=False, reads_typed_columns=bool(filters_str)
            ),
        ),
    ):
        rows_by_table[table] = await clickhouse_client.read_query_as_jsonl(
            query.replace("FORMAT ArrowStream", "FORMAT JSONEachRow"), parameters
        )
    return rows_by_table


@pytest.mark.parametrize(
    "filters,expected_events",
    [
        ([{"key": "properties.cart.plan = 'pro'", "type": "hogql"}], {"nested"}),
        ([{"key": "person.properties.org.tier = 'gold'", "type": "hogql"}], {"nested"}),
        ([{"key": "properties.cart = 'pro'", "type": "hogql"}], {"flat"}),
        ([{"key": "$feature/checkout", "type": "event", "operator": "exact", "value": ["true"]}], {"nested"}),
        ([{"key": "$os", "type": "event", "operator": "is_not_set"}], {"nested"}),
    ],
    ids=["nested-property", "nested-person-property", "top-level-property", "flag", "declared-property-not-set"],
)
@pytest.mark.django_db
async def test_native_recent_events_export_filters_like_the_native_events_export(
    clickhouse_client, ateam, settings, filters: list[dict], expected_events: set[str]
) -> None:
    settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA = True

    rows_by_table = await _read_native_exports(
        clickhouse_client, ateam.pk, _SENT_EVENTS, [BatchExportField(expression="event", alias="event")], filters
    )

    exported_events = {table: {row["event"] for row in rows} for table, rows in rows_by_table.items()}
    assert exported_events == {"events_json": expected_events, "events_json_recent": expected_events}


# Without filters `events_json_recent` is read as stored. A filter makes it the typed read.
@pytest.mark.parametrize("filters", [[], [{"key": "1 = 1", "type": "hogql"}]], ids=["stored-read", "typed-read"])
@pytest.mark.django_db
async def test_native_events_exports_read_ip_from_properties(clickhouse_client, ateam, settings, filters) -> None:
    settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA = True
    sent_events: dict[str, tuple[dict, dict]] = {
        "with-ip": ({"$ip": "203.0.113.7"}, {}),
        "empty-ip": ({"$ip": ""}, {}),
        "without-ip": ({"$browser": "Chrome"}, {}),
    }

    rows_by_table = await _read_native_exports(
        clickhouse_client,
        ateam.pk,
        sent_events,
        [BatchExportField(expression="event", alias="event"), BatchExportField(expression="ip", alias="ip")],
        filters,
    )

    expected_ips = {"with-ip": "203.0.113.7", "empty-ip": None, "without-ip": None}
    exported_ips = {table: {row["event"]: row["ip"] for row in rows} for table, rows in rows_by_table.items()}
    assert exported_ips == {"events_json": expected_ips, "events_json_recent": expected_ips}
