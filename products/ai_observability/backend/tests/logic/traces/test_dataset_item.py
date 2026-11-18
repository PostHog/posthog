from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.dataset_item import StepDatasetItem
from products.ai_observability.backend.logic.traces.node import NodeEvent
from products.ai_observability.backend.logic.traces.trace_queries import TraceNodeRow

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
MESSAGES = [{"role": "user", "content": "Why did my invoice go up?"}]


def node_event(event: str, properties: dict[str, Any]) -> NodeEvent:
    return NodeEvent(row=TraceNodeRow(uuid="node-1", event=event, timestamp=T0, properties=properties))


@parameterized.expand(
    [
        (
            "generation",
            node_event("$ai_generation", {"$ai_input": MESSAGES, "$ai_output_choices": MESSAGES, "plan": "pro"}),
            ("node-1", MESSAGES, MESSAGES, {"plan": "pro"}),
        ),
        (
            "embedding never has an output",
            node_event("$ai_embedding", {"$ai_input": "invoice", "$ai_output": [0.1]}),
            ("node-1", "invoice", None, {}),
        ),
        (
            "span saves its state",
            node_event("$ai_span", {"$ai_input_state": {"q": 1}, "$ai_output_state": {"a": 2}, "step": "lookup"}),
            ("node-1", {"q": 1}, {"a": 2}, {"step": "lookup"}),
        ),
        ("generation with nothing captured", node_event("$ai_generation", {}), ("node-1", {}, None, {})),
        (
            "root with a trace event carries no metadata",
            node_event("$ai_trace", {"$ai_input_state": {"q": 1}, "plan": "pro"}),
            ("trace-1", {"q": 1}, None, {}),
        ),
        ("root without a trace event", None, ("trace-1", {}, None, {})),
    ]
)
def test_builds_the_step_as_a_dataset_item(
    _name: str, event: NodeEvent | None, expected: tuple[str, Any, Any, dict[str, Any]]
) -> None:
    item = StepDatasetItem(trace_id="trace-1", trace_timestamp=T0, event=event)

    assert (item.source_event_id, item.input, item.source_output, item.metadata) == expected
