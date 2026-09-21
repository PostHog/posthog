from products.batch_exports.backend.temporal.sql.events import native_events_export_query


def test_native_events_export_query_refuses_stale_replicas() -> None:
    query = native_events_export_query("event")

    assert "max_replica_delay_for_distributed_queries=60" in query
    assert "fallback_to_stale_replicas_for_distributed_queries=0" in query
