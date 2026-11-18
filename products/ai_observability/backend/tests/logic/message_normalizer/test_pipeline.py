import pytest

import structlog
from parameterized import parameterized

from posthog.dataclasses import frozen

from products.ai_observability.backend.logic.message_normalizer.errors import RecipeRuntimeError
from products.ai_observability.backend.logic.message_normalizer.expressions import LiteralExpr
from products.ai_observability.backend.logic.message_normalizer.pipeline import RecipePipeline, RunOutcome, SlotCoercer
from products.ai_observability.backend.logic.message_normalizer.predicates import ExistsPredicate, Pattern
from products.ai_observability.backend.logic.message_normalizer.rules import (
    NO_MATCH,
    DispatchEngine,
    EmitSpec,
    Recipe,
    Rule,
)
from products.ai_observability.backend.logic.message_normalizer.scope import Scope
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, CompatMessage, Value

MATCH_ALL = Pattern(fields=())
MATCH_NONE = Pattern(fields=(("__absent", ExistsPredicate(should_exist=True)),))
COERCER = SlotCoercer()


@frozen
class StubRule(Rule):
    messages: list[CompatMessage]

    def produce(self, scope: Scope, engine: DispatchEngine, allow_drop: bool, depth: int) -> list[CompatMessage]:
        return self.messages


def stub(on: Pattern, messages: list[CompatMessage]) -> StubRule:
    return StubRule(on=on, followups=(), messages=messages)


def pipeline_of(*rules: Rule) -> RecipePipeline:
    return RecipePipeline([Recipe(id=f"r{index}", rules=(rule,)) for index, rule in enumerate(rules)])


def lit(value: Value) -> LiteralExpr:
    return LiteralExpr(value=value)


def scope(value: Value = None, role: str = "user") -> Scope:
    return Scope.for_node({} if value is None else value, role)


def test_the_first_matching_recipe_wins_and_is_recognized() -> None:
    pipeline = pipeline_of(
        stub(MATCH_NONE, [{"role": "user", "content": "never"}]),
        stub(MATCH_ALL, [{"role": "user", "content": "first-wins"}]),
        stub(MATCH_ALL, [{"role": "user", "content": "second"}]),
    )
    assert pipeline.run({"role": "user"}, "user") == RunOutcome(
        messages=({"role": "user", "content": "first-wins"},), recognized=True
    )


@parameterized.expand(
    [
        ("stringifies unclaimed input", {"weird": True}, "user", {"role": "user", "content": '{"weird":true}'}),
        (
            "keeps a string content field",
            {"content": "hi", "extra": 1},
            "assistant",
            {"role": "assistant", "content": "hi"},
        ),
        (
            "reads the role of unclaimed input",
            {"role": "system", "x": 1},
            "user",
            {"role": "system", "content": '{"role":"system","x":1}'},
        ),
    ]
)
def test_salvages_input_no_recipe_claims(_name: str, value: Value, role: str, expected: CompatMessage) -> None:
    assert pipeline_of(stub(MATCH_NONE, [])).run(value, role) == RunOutcome(messages=(expected,), recognized=False)


def test_delegation_salvages_an_unmatched_child_and_drops_a_missing_one() -> None:
    pipeline = pipeline_of(stub(MATCH_NONE, []))
    assert pipeline.dispatch({"weird": True}, "user", 0) == [{"role": "user", "content": '{"weird":true}'}]
    assert pipeline.dispatch(None, "user", 0) == [{"role": "user", "content": ""}]
    assert pipeline.dispatch(MISSING, "user", 0) is NO_MATCH


def test_delegation_past_the_max_depth_raises() -> None:
    with pytest.raises(RecipeRuntimeError, match="max depth"):
        pipeline_of(stub(MATCH_ALL, [])).dispatch({"role": "user"}, "user", 11)


TOOL_CALL: CompatMessage = {
    "type": "function",
    "id": "c1",
    "function": {"name": "get_weather", "arguments": {"city": "NYC"}},
}


@parameterized.expand(
    [
        ("role and content", EmitSpec(content=lit("hello")), "assistant", {"role": "assistant", "content": "hello"}),
        (
            "a role tag",
            EmitSpec(role="tool_result", content=lit("done")),
            "user",
            {"role": "assistant (tool result)", "content": "done"},
        ),
        (
            "a role expression",
            EmitSpec(role=lit("Human"), content=lit("x")),
            "assistant",
            {"role": "user", "content": "x"},
        ),
        (
            "a function-shaped tool call",
            EmitSpec(tool_call=lit(TOOL_CALL)),
            "user",
            {"role": "user", "content": "", "tool_calls": [TOOL_CALL]},
        ),
        (
            "a bare name and args tool call",
            EmitSpec(tool_call=lit({"id": "c2", "name": "search", "args": {"q": "hog"}})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [
                    {"type": "function", "id": "c2", "function": {"name": "search", "arguments": {"q": "hog"}}}
                ],
            },
        ),
        (
            "string arguments parsed",
            EmitSpec(tool_call=lit({"name": "search", "arguments": '{"q":"hog"}'})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "search", "arguments": {"q": "hog"}}}],
            },
        ),
        (
            "unparseable arguments kept",
            EmitSpec(tool_call=lit({"name": "search", "arguments": "{not json"})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "search", "arguments": "{not json"}}],
            },
        ),
        (
            "NaN arguments kept as text",
            EmitSpec(tool_call=lit({"name": "search", "arguments": '{"q": NaN}'})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "search", "arguments": '{"q": NaN}'}}],
            },
        ),
        (
            "overflowing float arguments kept as text",
            EmitSpec(tool_call=lit({"name": "search", "arguments": '{"q": 1e999}'})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "search", "arguments": '{"q": 1e999}'}}],
            },
        ),
        (
            "null args fall through to arguments",
            EmitSpec(tool_call=lit({"name": "s", "args": None, "arguments": {"q": 1}})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "s", "arguments": {"q": 1}}}],
            },
        ),
        (
            "empty string args win",
            EmitSpec(tool_call=lit({"name": "s", "args": "", "arguments": {"q": 1}})),
            "user",
            {
                "role": "user",
                "content": "",
                "tool_calls": [{"type": "function", "function": {"name": "s", "arguments": ""}}],
            },
        ),
        (
            "a single text item collapses",
            EmitSpec(content=lit(["only one"])),
            "user",
            {"role": "user", "content": "only one"},
        ),
        (
            "several texts become text parts",
            EmitSpec(content=lit(["a", "b"])),
            "user",
            {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
        ),
        ("missing content defaults to empty", EmitSpec(role="user"), "assistant", {"role": "user", "content": ""}),
        (
            "spread fills while explicit slots win",
            EmitSpec(spread=lit({"content": "from spread", "extra": 1}), role="system", content=lit("override")),
            "user",
            {"role": "system", "content": "override", "extra": 1},
        ),
        (
            "a list function is not a function mapping, even beside a name",
            EmitSpec(tool_call=lit({"type": "function", "function": ["x"], "name": "search", "args": {"q": 1}})),
            "user",
            {"role": "user", "content": ""},
        ),
        (
            "an empty tool_calls clears the spread's",
            EmitSpec(spread=lit({"tool_calls": [TOOL_CALL]}), tool_calls=lit([])),
            "user",
            {"role": "user", "content": ""},
        ),
    ]
)
def test_builds_messages(_name: str, emit: EmitSpec, role: str, expected: CompatMessage) -> None:
    assert COERCER.build_message(emit, scope(role=role)) == expected


def test_drops_an_empty_message_when_allowed() -> None:
    assert COERCER.build_message(EmitSpec(role="user"), scope(), allow_drop=True) is None


def test_non_text_content_renders_empty_and_logs_its_type() -> None:
    with structlog.testing.capture_logs() as logs:
        message = COERCER.build_message(EmitSpec(content=lit({"unexpected": "object"})), scope())
    assert message == {"role": "user", "content": ""}
    assert [log["event"] for log in logs] == ["llma_recipe_produced_non_text_content"]


@parameterized.expand(
    [
        (
            "overrides role and tool call id",
            EmitSpec(role="tool_result", tool_call_id=lit("tc1")),
            {"role": "assistant (tool result)", "content": "r", "tool_call_id": "tc1"},
        ),
        ("leaves fields without slots", EmitSpec(), {"role": "user", "content": "r"}),
    ]
)
def test_stamps_a_built_message(_name: str, emit: EmitSpec, expected: CompatMessage) -> None:
    assert COERCER.stamp({"role": "user", "content": "r"}, emit, scope()) == expected
