import pytest

from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.sql.events import native_events_export_query

QUERY_PARAMETERS: dict[str, object] = {
    "team_id": 1,
    "interval_start": None,
    "interval_end": "2026-01-01 00:00:00",
    "include_events": [],
    "exclude_events": [],
}


def test_native_events_export_query_refuses_stale_replicas() -> None:
    query = native_events_export_query("event")

    assert "max_replica_delay_for_distributed_queries=60" in query
    assert "fallback_to_stale_replicas_for_distributed_queries=0" in query


def test_native_events_export_query_keeps_empty_object_literals() -> None:
    query = ClickHouseClient().prepare_query(native_events_export_query("event"), QUERY_PARAMETERS)

    assert "'{0}'" not in query
    assert "'{}'" in query


# Without these settings `toJSONString(properties)` prints a stored dotted key as `a%2Eb` and a `/` as `\/`.
@pytest.mark.parametrize("setting", ["json_type_escape_dots_in_keys=1", "output_format_json_escape_forward_slashes=0"])
def test_native_events_export_query_matches_legacy_json_text(setting: str) -> None:
    assert setting in native_events_export_query("event")
