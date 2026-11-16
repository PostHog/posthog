from parameterized import parameterized

from products.ai_observability.backend.logic.traces.node_ids import NodeIdResolver, NodeIds


@parameterized.expand(
    [
        ("an event uuid", "e1", "e1"),
        ("a generation id", "gen-a", "e1"),
        ("a span id", "span-a", "e0"),
        ("an unknown id", "nope", None),
    ]
)
def test_resolve(_name: str, node_id: str, expected: str | None) -> None:
    resolver = NodeIdResolver(
        [
            NodeIds(uuid="e0", generation_id=None, span_id="span-a"),
            NodeIds(uuid="e1", generation_id="gen-a", span_id="span-b"),
        ]
    )

    assert resolver.resolve(node_id) == expected
