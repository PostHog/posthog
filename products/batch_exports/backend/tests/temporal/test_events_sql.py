import json

import pytest

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import EVENTS_JSON_CLEANER, EVENTS_PROPERTIES_JSON_TYPE
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.sql.events import (
    _NATIVE_EVENTS_FIELD_EXPRESSIONS,
    native_events_export_query,
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
    "sent_properties,expected",
    [
        ({"cart": {"items": 2, "note": None}, "tags": ["a"]}, {"cart": {"items": 2, "note": None}, "tags": ["a"]}),
        (
            {"$browser": "Firefox", "$feature/checkout": True},
            {"$browser": "Firefox", "$feature_flags": {"checkout": "true"}},
        ),
    ],
    ids=["no-flags-or-built-in-properties", "flags-and-built-in-properties"],
)
@pytest.mark.django_db
def test_native_events_export_sends_properties_without_storage_defaults(
    sent_properties: dict[str, object], expected: dict[str, object]
) -> None:
    """The exported document puts back what the ingestion cleaner stores as text, and leaves out its defaults."""
    result = sync_execute(
        f"SELECT {_NATIVE_EVENTS_FIELD_EXPRESSIONS['properties']} FROM ("
        f"SELECT CAST(cleaned.properties, '{EVENTS_PROPERTIES_JSON_TYPE()}') AS properties "
        f"FROM (SELECT {EVENTS_JSON_CLEANER}(%(properties)s, '{{}}') AS cleaned)"
        ") AS events",
        {"properties": json.dumps(sent_properties)},
    )

    assert json.loads(result[0][0]) == expected
