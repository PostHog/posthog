import json
from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.node import FAILED_STEP_MESSAGE, IOKeys, NodeEvent, NodeMetadata
from products.ai_observability.backend.logic.traces.trace_queries import TraceNodeRow

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
MESSAGES = [{"role": "user", "content": "Why did my invoice go up?"}]
NO_METADATA = NodeMetadata(provider=None, temperature=None, session_id=None, prompt_name=None, prompt_version=None)


def node_event(event: str, properties: dict[str, Any]) -> NodeEvent:
    return NodeEvent(row=TraceNodeRow(uuid="node-1", event=event, timestamp=T0, properties=properties))


@parameterized.expand(
    [
        (
            "generation",
            "$ai_generation",
            {"$ai_input": MESSAGES, "$ai_output_choices": MESSAGES, "$ai_tools": []},
            IOKeys(input="$ai_input", output="$ai_output_choices", tools="$ai_tools"),
        ),
        (
            "generation with a plain output",
            "$ai_generation",
            {"$ai_input": MESSAGES, "$ai_output": "Two seats were added."},
            IOKeys(input="$ai_input", output="$ai_output", tools=None),
        ),
        (
            "generation whose output choices are null",
            "$ai_generation",
            {"$ai_output_choices": None, "$ai_output": "Two seats were added."},
            IOKeys(input=None, output="$ai_output", tools=None),
        ),
        ("generation with nothing captured", "$ai_generation", {}, IOKeys(input=None, output=None, tools=None)),
        (
            "embedding never has an output",
            "$ai_embedding",
            {"$ai_input": "invoice", "$ai_output": [0.1, 0.2]},
            IOKeys(input="$ai_input", output=None, tools=None),
        ),
        (
            "span state",
            "$ai_span",
            {"$ai_input_state": {"question": "x"}, "$ai_output_state": {"answer": "y"}},
            IOKeys(input="$ai_input_state", output="$ai_output_state", tools=None),
        ),
        (
            "OTel span with messages before its state",
            "$ai_span",
            {"$ai_input": MESSAGES, "$ai_output_choices": MESSAGES, "$ai_input_state": {"question": "x"}},
            IOKeys(input="$ai_input", output="$ai_output_choices", tools=None),
        ),
        ("span never has tools", "$ai_span", {"$ai_tools": []}, IOKeys(input=None, output=None, tools=None)),
        (
            "trace event state",
            "$ai_trace",
            {"$ai_input_state": {"question": "x"}, "$ai_output_state": {"answer": "y"}},
            IOKeys(input="$ai_input_state", output="$ai_output_state", tools=None),
        ),
        (
            "trace event with messages and state prefers the state",
            "$ai_trace",
            {
                "$ai_input": MESSAGES,
                "$ai_input_state": {"question": "x"},
                "$ai_output_choices": MESSAGES,
                "$ai_output_state": {"answer": "y"},
            },
            IOKeys(input="$ai_input_state", output="$ai_output_state", tools=None),
        ),
    ]
)
def test_io_keys(_name: str, event: str, properties: dict[str, Any], expected: IOKeys) -> None:
    assert node_event(event, properties).io_keys == expected


@parameterized.expand(
    [
        ("text error", {"$ai_error": "Rate limited"}, "Rate limited"),
        ("structured error", {"$ai_error": {"message": "boom"}}, json.dumps({"message": "boom"}, indent=2)),
        ("flag without a message", {"$ai_is_error": True}, FAILED_STEP_MESSAGE),
        ("SDK-serialized flag with an empty message", {"$ai_is_error": "true", "$ai_error": ""}, FAILED_STEP_MESSAGE),
        ("empty message without a flag", {"$ai_error": ""}, None),
        ("flag off", {"$ai_is_error": False}, None),
    ]
)
def test_error(_name: str, properties: dict[str, Any], expected: str | None) -> None:
    assert node_event("$ai_span", properties).error == expected


@parameterized.expand(
    [
        (
            "values as sent",
            {
                "$ai_provider": "openai",
                "$ai_temperature": 0.2,
                "$ai_session_id": "sess-1",
                "$ai_prompt_name": "billing-answer",
                "$ai_prompt_version": 6,
            },
            NodeMetadata(
                provider="openai",
                temperature=0.2,
                session_id="sess-1",
                prompt_name="billing-answer",
                prompt_version=6.0,
            ),
        ),
        (
            "numbers sent as text and empty text",
            {"$ai_temperature": "0.2", "$ai_session_id": "", "$ai_prompt_version": "6"},
            NodeMetadata(provider=None, temperature=0.2, session_id=None, prompt_name=None, prompt_version=6.0),
        ),
        ("values that are not numbers", {"$ai_temperature": "warm", "$ai_prompt_version": float("inf")}, NO_METADATA),
    ]
)
def test_metadata(_name: str, properties: dict[str, Any], expected: NodeMetadata) -> None:
    assert node_event("$ai_generation", properties).metadata == expected
