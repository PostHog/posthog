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
        totals_partial=False,
        cost_and_latency_partial=False,
        tree=[
            contracts.TraceNode(
                id="trace-1",
                kind="trace",
                name="Trace",
                label="Trace",
                model=None,
                stats=stats,
                has_error=False,
                children=[],
            )
        ],
        timeline=[],
        total_ms=0.0,
        thread_node_ids=[],
        default_node_id="trace-1",
        node_ids_by_alias={},
        git=None,
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
        "totalsPartial",
        "costAndLatencyPartial",
        "tree",
        "timeline",
        "totalMs",
        "threadNodeIds",
        "defaultNodeId",
        "nodeIdsByAlias",
        "git",
    }
    assert dumped["totals"]["cacheWriteTokens"] is None
    assert dumped["person"] == {"distinctId": "user-1", "label": "ada@example.com"}
    schema = contracts.TraceNode.model_json_schema(mode="serialization")
    assert set(schema["$defs"]["TraceNode"]["required"]) == {
        "id",
        "kind",
        "name",
        "label",
        "model",
        "stats",
        "hasError",
        "children",
    }


def _all_subclasses(cls: type[contracts.Contract]) -> list[type[contracts.Contract]]:
    subclasses: list[type[contracts.Contract]] = []
    for direct in cls.__subclasses__():
        subclasses.extend([direct, *_all_subclasses(direct)])
    return subclasses


def test_no_contract_field_or_alias_starts_with_a_dollar() -> None:
    offenders = []
    for cls in _all_subclasses(contracts.Contract):
        fields = {**cls.model_fields, **cls.model_computed_fields}
        for field_name, field in fields.items():
            aliases = [getattr(field, attr, None) for attr in ("alias", "serialization_alias", "validation_alias")]
            if any(isinstance(alias, str) and alias.startswith("$") for alias in aliases):
                offenders.append(f"{cls.__name__}.{field_name}")

    assert offenders == [], (
        f"Contract fields never use $ or $ai_ names (products/ai_observability/AGENTS.md): {offenders}"
    )
