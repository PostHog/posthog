from collections.abc import Callable
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.message_normalizer.errors import RecipeTimeoutError
from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.traces.step_content import step_content

TEAM_ID = 7
CONVERSATION = [{"role": "user", "content": "Hi"}]
REPLY = [{"role": "assistant", "content": "Hello"}]


def content_of(
    kind: contracts.TraceNodeKind,
    input_value: Any,
    output_value: Any,
    build_normalizer: Callable[[], RecipeNormalizer] = RecipeNormalizer,
):
    return step_content(kind, "node-1", input_value, output_value, build_normalizer=build_normalizer, team_id=TEAM_ID)


def texts(side: contracts.TraceMessagesSide | contracts.TraceJsonSide) -> list[str]:
    assert isinstance(side, contracts.TraceMessagesSide)
    return [
        part.text for message in side.messages for part in message.parts if isinstance(part, contracts.TraceTextPart)
    ]


def test_generation_sides_are_messages_with_their_default_roles_and_prefixes():
    content = content_of("generation", "Hi", "Hello")

    assert isinstance(content.input, contracts.TraceMessagesSide)
    assert isinstance(content.output, contracts.TraceMessagesSide)
    assert [(m.id, m.role) for m in content.input.messages] == [("node-1-in-0", "user")]
    assert [(m.id, m.role) for m in content.output.messages] == [("node-1-out-0", "assistant")]
    assert {m.source_node_id for m in [*content.input.messages, *content.output.messages]} == {"node-1"}


@parameterized.expand([("none", None), ("empty_string", "")])
def test_empty_side_on_a_messages_step_has_no_messages(_name, empty):
    content = content_of("generation", empty, "Hello")

    assert content.input == contracts.TraceMessagesSide(kind="messages", messages=[])
    assert texts(content.output) == ["Hello"]


def test_span_with_message_lists_on_both_sides_is_messages():
    content = content_of("span", CONVERSATION, REPLY)

    assert texts(content.input) == ["Hi"]
    assert texts(content.output) == ["Hello"]


def test_span_keeps_a_wrapped_conversation_as_json():
    input_value: dict[str, Any] = {"conflicts": []}
    output_value = {"messages": REPLY}

    content = content_of("span", input_value, output_value)

    assert content.input == contracts.TraceJsonSide(kind="json", value=input_value)
    assert content.output == contracts.TraceJsonSide(kind="json", value=output_value)


@parameterized.expand(
    [
        ("string_with_messages", "plain input", REPLY, True, True),
        ("messages_with_string", CONVERSATION, "plain output", True, True),
        ("empty_with_messages", None, REPLY, True, True),
        ("string_with_object", "plain input", {"k": 1}, False, False),
        ("object_with_object", {"k": 1}, {"j": 2}, False, False),
        ("string_with_string", "a", "b", False, False),
        ("both_empty", None, "", False, False),
        ("object_with_messages", {"k": 1}, REPLY, False, True),
    ]
)
def test_span_side_kinds(_name, input_value, output_value, input_is_messages, output_is_messages):
    content = content_of("span", input_value, output_value)

    assert (content.input.kind == "messages", content.output.kind == "messages") == (
        input_is_messages,
        output_is_messages,
    )


def test_string_side_following_a_message_list_becomes_one_message_with_its_default_role():
    content = content_of("trace", "plain input", REPLY)

    assert isinstance(content.input, contracts.TraceMessagesSide)
    assert [(m.id, m.role) for m in content.input.messages] == [("node-1-in-0", "user")]
    assert texts(content.input) == ["plain input"]


def test_a_step_whose_sides_are_json_never_builds_the_normalizer():
    build_normalizer = MagicMock(side_effect=RecipeNormalizer)

    content_of("span", {"k": 1}, {"j": 2}, build_normalizer)
    assert build_normalizer.call_count == 0

    content_of("generation", "Hi", "Hello", build_normalizer)
    assert build_normalizer.call_count == 1


@parameterized.expand(
    [
        ("list_type_on_a_span_item", "span", [{"type": ["human"], "content": "a"}], "json"),
        ("object_type_on_a_span_item", "span", [{"type": {"name": "human"}, "content": "a"}], "json"),
        ("list_type_on_a_content_item", "generation", [{"role": "user", "content": [{"type": ["text"]}]}], "messages"),
        ("object_type_on_a_content_item", "generation", [{"role": "user", "content": [{"type": {}}]}], "messages"),
    ]
)
def test_an_unhashable_item_type_renders_without_failing_the_side(_name, kind, input_value, input_kind):
    with patch("products.ai_observability.backend.logic.traces.step_content.logger") as logger:
        content = content_of(kind, input_value, REPLY)

    assert (content.input.kind, content.output.kind) == (input_kind, "messages")
    logger.warning.assert_not_called()


def failing_output(error: Exception) -> Callable[[], RecipeNormalizer]:
    class OutputFails(RecipeNormalizer):
        def normalize_messages(self, value, default_role, tools=None):
            if default_role == "assistant":
                raise error
            return super().normalize_messages(value, default_role)

    return OutputFails


@parameterized.expand(
    [
        ("recipe_timeout", RecipeTimeoutError("too slow"), "RecipeTimeoutError", False),
        ("recursion", RecursionError(), "RecursionError", True),
        ("unexpected", KeyError("boom"), "KeyError", True),
    ]
)
def test_failing_side_falls_back_to_json(_name, error, error_class, reported):
    with (
        patch("products.ai_observability.backend.logic.traces.step_content.logger") as logger,
        patch("products.ai_observability.backend.logic.traces.step_content.capture_exception") as capture,
    ):
        content = content_of("generation", "Hi", REPLY, failing_output(error))

    assert texts(content.input) == ["Hi"]
    assert content.output == contracts.TraceJsonSide(kind="json", value=REPLY)
    logger.warning.assert_called_once_with(
        "trace_step_content_fallback",
        team_id=TEAM_ID,
        node_kind="generation",
        error_class=error_class,
        exc_info=reported,
    )
    assert capture.called is reported


def test_span_failing_side_falls_back_to_the_original_value():
    wrapped = {"messages": REPLY}

    content = content_of("span", CONVERSATION, wrapped, failing_output(RecipeTimeoutError("too slow")))

    assert content.output == contracts.TraceJsonSide(kind="json", value=wrapped)


def test_deeply_nested_tool_result_stays_text_and_the_response_serializes():
    nested = "[" * 2000 + "]" * 2000
    output = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"type": "function", "id": "c", "function": {"name": "f", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c", "content": nested},
    ]

    content = content_of("generation", "Hi", output)

    assert isinstance(content.output, contracts.TraceMessagesSide)
    [call] = content.output.messages[0].parts
    assert isinstance(call, contracts.TraceToolCallPart) and call.result == nested
    content.model_dump_json()
