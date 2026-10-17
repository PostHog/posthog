from datetime import UTC, datetime

from products.ai_observability.backend.facade import contracts


def test_trace_dumps_declared_fields_in_camel_case_and_every_field_is_required_in_the_schema() -> None:
    stats = contracts.TraceNodeStats(
        cost_usd=0.5,
        input_tokens=3,
        output_tokens=4,
        cache_read_tokens=None,
        cache_write_tokens=None,
        latency_ms=1200.0,
    )
    trace = contracts.Trace(
        id="trace-1",
        name=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        session_id=None,
        person=contracts.TracePerson(distinct_id="user-1", label="ada@example.com"),
        totals=stats,
        has_error=False,
        error_count=0,
        tree=[
            contracts.TraceNode(
                id="trace-1", kind="trace", name="Trace", model=None, stats=stats, has_error=False, children=[]
            )
        ],
        timeline=[],
        total_ms=0.0,
        thread_node_ids=[],
    )

    dumped = trace.model_dump(mode="json", by_alias=True)

    assert set(dumped) == {
        "id",
        "name",
        "createdAt",
        "sessionId",
        "person",
        "totals",
        "hasError",
        "errorCount",
        "tree",
        "timeline",
        "totalMs",
        "threadNodeIds",
    }
    assert dumped["totals"]["cacheWriteTokens"] is None
    assert dumped["person"] == {"distinctId": "user-1", "label": "ada@example.com"}
    schema = contracts.TraceNode.model_json_schema(mode="serialization")
    assert set(schema["$defs"]["TraceNode"]["required"]) == {
        "id",
        "kind",
        "name",
        "model",
        "stats",
        "hasError",
        "children",
    }
