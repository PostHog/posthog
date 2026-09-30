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
    for key in ("$set", "$set_once", "$group_set"):
        assert f"temporary_properties.^`{key}`), '{{}}')" in query
