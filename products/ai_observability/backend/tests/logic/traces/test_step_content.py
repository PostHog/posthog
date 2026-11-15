from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.message_normalizer import (
    normalizer as normalizer_module,
    run_limits as run_limits_module,
)
from products.ai_observability.backend.logic.message_normalizer.errors import RecipeTimeoutError
from products.ai_observability.backend.logic.message_normalizer.normalizer import (
    RecipeNormalizer,
    StoredRecipe,
    compile_stored_recipe,
    merge_recipes,
)
from products.ai_observability.backend.logic.message_normalizer.pipeline import RecipePipeline
from products.ai_observability.backend.logic.traces.step_content import (
    NODE_READ_TIME_LIMIT_SECONDS,
    read_step,
    step_content,
)

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


def with_team_recipe(source: str) -> Callable[[], RecipeNormalizer]:
    recipe = compile_stored_recipe(StoredRecipe(id="team-recipe", source=source))
    assert recipe is not None
    return lambda: RecipeNormalizer(merge_recipes([recipe]))


AGENT_RECIPE = "rules:\n  - on: { who: agent }\n    emit: { role: assistant, content: $.said }\n"
NEVER_MATCHING_RECIPE = "rules:\n  - on: { never: { exists: true } }\n    emit: { content: $ }\n"
MATCH_EVERYTHING_RECIPE = "rules:\n  - on: { $: { exists: true } }\n    emit: { content: $ }\n"


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


def test_span_unwraps_a_conversation_whose_only_key_is_messages():
    input_value: dict[str, Any] = {"conflicts": []}

    content = content_of("span", input_value, {"messages": REPLY})

    assert content.input == contracts.TraceJsonSide(kind="json", value=input_value)
    assert texts(content.output) == ["Hello"]


def test_a_span_prompt_value_renders_its_system_prompt_as_system():
    system = {
        "lc": 1,
        "type": "constructor",
        "id": ["langchain_core", "messages", "SystemMessage"],
        "kwargs": {"content": "Be brief."},
    }
    prompt_value = {
        "lc": 1,
        "type": "constructor",
        "id": ["langchain_core", "prompt_values", "ChatPromptValue"],
        "kwargs": {"messages": [system]},
    }

    content = content_of("span", prompt_value, REPLY)

    assert isinstance(content.input, contracts.TraceMessagesSide)
    assert [m.role for m in content.input.messages] == ["system"]
    assert texts(content.input) == ["Be brief."]


def test_a_serialized_tool_result_folds_into_its_tool_call():
    def serialized(cls: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {"lc": 1, "type": "constructor", "id": ["langchain_core", "messages", cls], "kwargs": kwargs}

    call = {"name": "search", "args": {"q": "x"}, "id": "c1", "type": "tool_call"}
    conversation = [
        serialized("AIMessage", {"content": "", "tool_calls": [call]}),
        serialized("ToolMessage", {"content": [{"type": "text", "text": "42"}], "tool_call_id": "c1"}),
    ]

    content = content_of("span", {"k": 1}, conversation)

    assert isinstance(content.output, contracts.TraceMessagesSide)
    [message] = content.output.messages
    [part] = message.parts
    assert isinstance(part, contracts.TraceToolCallPart)
    assert (part.name, part.result) == ("search", "42")


def test_a_generation_wrapping_messages_is_not_unwrapped():
    content = content_of("generation", {"messages": CONVERSATION}, "Hello")

    assert isinstance(content.input, contracts.TraceMessagesSide)
    assert [m.role for m in content.input.messages] == ["user"]
    assert texts(content.input) == ['{"messages":[{"role":"user","content":"Hi"}]}']


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


def test_a_normalizer_that_fails_to_build_is_tried_and_reported_once_per_read():
    build_normalizer = MagicMock(side_effect=RuntimeError("boom"))

    with patch("products.ai_observability.backend.logic.traces.step_content.capture_exception") as capture:
        content = content_of("generation", "Hi", "Hello", build_normalizer)

    assert (content.input.kind, content.output.kind) == ("json", "json")
    assert build_normalizer.call_count == 1
    assert capture.call_count == 1


def test_a_json_span_side_builds_the_normalizer_once_and_stays_json_without_team_recipes():
    build_normalizer = MagicMock(side_effect=RecipeNormalizer)

    content = content_of("span", {"k": 1}, {"j": 2}, build_normalizer)

    assert (content.input.kind, content.output.kind) == ("json", "json")
    assert build_normalizer.call_count == 1


def test_a_span_side_a_team_recipe_recognizes_renders_as_messages():
    content = content_of("span", {"who": "agent", "said": "Hi"}, {"k": 1}, with_team_recipe(AGENT_RECIPE))

    assert isinstance(content.input, contracts.TraceMessagesSide)
    assert [m.role for m in content.input.messages] == ["assistant"]
    assert texts(content.input) == ["Hi"]
    assert content.output == contracts.TraceJsonSide(kind="json", value={"k": 1})


def test_a_span_side_only_a_builtin_recognizes_stays_json():
    content = content_of("span", [{"foo": 1}], {"k": 1}, with_team_recipe(NEVER_MATCHING_RECIPE))

    assert content.input == contracts.TraceJsonSide(kind="json", value=[{"foo": 1}])


def timed_runs(run_cost: Callable[[Any], float]) -> tuple[SimpleNamespace, type[RecipePipeline]]:
    clock = SimpleNamespace(now=0.0)

    class TimedPipeline(RecipePipeline):
        def run(self, value, default_role, *, salvages=True):
            clock.now += run_cost(value)
            return super().run(value, default_role, salvages=salvages)

    return clock, TimedPipeline


def test_a_team_recipe_check_that_runs_out_the_deadline_leaves_the_other_sides_conversation():
    slow_input = {"documents": ["..."]}
    clock, pipeline = timed_runs(lambda value: 2 * NODE_READ_TIME_LIMIT_SECONDS if value == slow_input else 0)

    with (
        patch.object(run_limits_module, "time", SimpleNamespace(monotonic=lambda: clock.now)),
        patch.object(normalizer_module, "RecipePipeline", pipeline),
    ):
        content = content_of("span", slow_input, REPLY, with_team_recipe(AGENT_RECIPE))

    assert content.input == contracts.TraceJsonSide(kind="json", value=slow_input)
    assert texts(content.output) == ["Hello"]


def test_a_matched_team_recipe_runs_once_so_a_slow_recipe_still_fits_the_deadline():
    clock, pipeline = timed_runs(lambda value: 0.6 * NODE_READ_TIME_LIMIT_SECONDS if "who" in value else 0)

    with (
        patch.object(run_limits_module, "time", SimpleNamespace(monotonic=lambda: clock.now)),
        patch.object(normalizer_module, "RecipePipeline", pipeline),
    ):
        content = content_of("span", {"who": "agent", "said": "Hi"}, {"k": 1}, with_team_recipe(AGENT_RECIPE))

    assert texts(content.input) == ["Hi"]


def test_a_team_recipe_check_on_an_unmatched_side_builds_no_fallback_text():
    too_deep_to_serialize: dict[str, Any] = {}
    cursor = too_deep_to_serialize
    for _ in range(100_000):
        cursor["a"] = {}
        cursor = cursor["a"]

    with structlog.testing.capture_logs() as logs:
        content = content_of("span", too_deep_to_serialize, {"j": 2}, with_team_recipe(AGENT_RECIPE))

    assert content.input.kind == "json"
    assert [log["event"] for log in logs if log["event"] == "trace_step_content_fallback"] == []


def test_a_team_recipe_match_that_renders_nothing_leaves_the_span_side_json():
    content = content_of("span", {"k": 1}, {"j": 2}, with_team_recipe(MATCH_EVERYTHING_RECIPE))

    assert content.input == contracts.TraceJsonSide(kind="json", value={"k": 1})


def test_a_team_normalizer_that_fails_to_build_leaves_a_json_span_side_json():
    build_normalizer = MagicMock(side_effect=RecipeTimeoutError("deadline"))

    content = content_of("span", {"k": 1}, {"j": 2}, build_normalizer)

    assert content.input == contracts.TraceJsonSide(kind="json", value={"k": 1})


def test_a_generation_renders_the_same_with_a_team_recipe_that_matches_nothing():
    assert content_of("generation", CONVERSATION, REPLY, with_team_recipe(NEVER_MATCHING_RECIPE)) == content_of(
        "generation", CONVERSATION, REPLY
    )


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


AGENT_SAID = {"who": "agent", "said": "Hi"}


@parameterized.expand(
    [
        ("conversations", "generation", CONVERSATION, REPLY, RecipeNormalizer, (True, True)),
        ("salvaged generation input", "generation", AGENT_SAID, REPLY, RecipeNormalizer, (False, True)),
        ("json span input beside an empty output", "span", AGENT_SAID, None, RecipeNormalizer, (False, True)),
        ("span input a team recipe parses", "span", AGENT_SAID, None, with_team_recipe(AGENT_RECIPE), (True, True)),
        (
            "span input a team recipe matches but renders nothing for",
            "span",
            {"k": 1},
            None,
            with_team_recipe(MATCH_EVERYTHING_RECIPE),
            (False, True),
        ),
        ("empty span sides", "span", "", None, RecipeNormalizer, (True, True)),
        (
            "generation output whose message is empty",
            "generation",
            CONVERSATION,
            [{"role": "assistant", "content": ""}],
            RecipeNormalizer,
            (True, True),
        ),
        ("span output that is plain text", "span", AGENT_SAID, "done", RecipeNormalizer, (False, True)),
        ("span output that is a number", "span", AGENT_SAID, 42, RecipeNormalizer, (False, True)),
        ("span output that is an empty object", "span", AGENT_SAID, {}, RecipeNormalizer, (False, True)),
        ("span output that is an array", "span", AGENT_SAID, [1, 2], RecipeNormalizer, (False, False)),
        (
            "generation input a team recipe matches but renders nothing for",
            "generation",
            {"k": {"x": 1}},
            REPLY,
            with_team_recipe(MATCH_EVERYTHING_RECIPE),
            (False, True),
        ),
    ]
)
def test_read_step_reports_whether_each_side_was_recognized(
    _name, kind, input_value, output_value, build_normalizer, expected
):
    reading = read_step(kind, "node-1", input_value, output_value, build_normalizer=build_normalizer, team_id=TEAM_ID)

    assert (reading.input.recognized, reading.output.recognized) == expected


@parameterized.expand(
    [
        ("a bounded failure carries its message", RecipeTimeoutError("too slow"), "too slow"),
        ("an unexpected failure carries none", KeyError("boom"), None),
    ]
)
def test_a_side_that_fails_is_unrecognized(_name, error, runtime_error):
    with patch("products.ai_observability.backend.logic.traces.step_content.capture_exception"):
        reading = read_step(
            "generation", "node-1", "Hi", REPLY, build_normalizer=failing_output(error), team_id=TEAM_ID
        )

    assert (reading.output.recognized, reading.output.runtime_error) == (False, runtime_error)
    assert reading.input.recognized
