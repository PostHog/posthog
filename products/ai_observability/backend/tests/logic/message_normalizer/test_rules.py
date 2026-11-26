from collections.abc import Callable

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.expressions import LiteralExpr
from products.ai_observability.backend.logic.message_normalizer.predicates import Pattern
from products.ai_observability.backend.logic.message_normalizer.rules import (
    NO_MATCH,
    DelegateEachRule,
    DelegateRule,
    DispatchResult,
    EmitRule,
    EmitSpec,
    ExpandFollowup,
    Followup,
    StaticFollowup,
)
from products.ai_observability.backend.logic.message_normalizer.scope import Scope
from products.ai_observability.backend.logic.message_normalizer.values import CompatMessage, Value, to_text

type Build = Callable[[EmitSpec, Scope, bool], CompatMessage | None]

SCOPE = Scope.for_node({"role": "assistant"}, "user")
ANYTHING = Pattern(fields=())


class FakeBuilder:
    def __init__(self, build: Build) -> None:
        self._build = build

    def build_message(self, emit: EmitSpec, scope: Scope, allow_drop: bool = False) -> CompatMessage | None:
        return self._build(emit, scope, allow_drop)

    def stamp(self, message: CompatMessage, emit: EmitSpec, scope: Scope) -> CompatMessage:
        return {**message, "tool_call_id": "parent"}


class FakeEngine:
    def __init__(self, results: list[DispatchResult] | None = None, build: Build | None = None) -> None:
        self._results = list(results or [])
        self.dispatched: list[tuple[Value, str, int]] = []
        self.coercer = FakeBuilder(build or (lambda emit, scope, allow_drop: None))

    def dispatch(self, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        self.dispatched.append((value, inherited_role, depth))
        return self._results.pop(0)


def content_of_scope(emit: EmitSpec, scope: Scope, allow_drop: bool) -> CompatMessage:
    return {"role": "user", "content": to_text(scope.value)}


@parameterized.expand(
    [
        (
            "a static followup",
            (StaticFollowup(emit=EmitSpec()),),
            content_of_scope,
            [{"role": "user", "content": '{"role":"assistant"}'}],
        ),
        (
            "an expand over a list",
            (ExpandFollowup(source=LiteralExpr(value=["a", "b"]), each=EmitSpec()),),
            content_of_scope,
            [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        ),
        ("a followup the coercer drops", (StaticFollowup(emit=EmitSpec()),), lambda emit, scope, allow_drop: None, []),
        (
            "an expand over a non-list",
            (ExpandFollowup(source=LiteralExpr(value="nope"), each=EmitSpec()),),
            content_of_scope,
            [],
        ),
    ]
)
def test_builds_followups(
    _name: str, followups: tuple[Followup, ...], build: Build, expected: list[CompatMessage]
) -> None:
    rule = EmitRule(on=ANYTHING, followups=followups, emit=EmitSpec())
    assert rule.build_followups(SCOPE, FakeEngine(build=build)) == expected


def test_static_followups_may_be_dropped_when_empty() -> None:
    seen: list[bool] = []

    def record(emit: EmitSpec, scope: Scope, allow_drop: bool) -> None:
        seen.append(allow_drop)

    EmitRule(on=ANYTHING, followups=(StaticFollowup(emit=EmitSpec()),), emit=EmitSpec()).build_followups(
        SCOPE, FakeEngine(build=record)
    )
    assert seen == [True]


@parameterized.expand(
    [
        ("a built message", {"role": "user", "content": "hi"}, [{"role": "user", "content": "hi"}]),
        ("a dropped message", None, []),
    ]
)
def test_emit_rule_produces_what_the_coercer_builds(
    _name: str, built: CompatMessage | None, expected: list[CompatMessage]
) -> None:
    rule = EmitRule(on=ANYTHING, followups=(), emit=EmitSpec())
    assert rule.produce(SCOPE, FakeEngine(build=lambda emit, scope, allow_drop: built), True, 0) == expected


def test_delegate_redispatches_at_the_next_depth_with_the_resolved_role() -> None:
    engine = FakeEngine(results=[[{"role": "assistant", "content": "delegated"}]])
    rule = DelegateRule(on=ANYTHING, followups=(), source=LiteralExpr(value={"unwrapped": True}))
    assert rule.produce(SCOPE, engine, False, 3) == [{"role": "assistant", "content": "delegated"}]
    assert engine.dispatched == [({"unwrapped": True}, "assistant", 4)]


def test_delegate_returns_nothing_when_no_recipe_matches() -> None:
    rule = DelegateRule(on=ANYTHING, followups=(), source=LiteralExpr(value="anything"))
    assert rule.produce(SCOPE, FakeEngine(results=[NO_MATCH]), False, 0) == []


@parameterized.expand(
    [
        (
            "concatenates each element's messages",
            [[{"role": "user", "content": "a"}], [{"role": "user", "content": "b"}]],
            None,
            [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        ),
        (
            "skips elements no recipe matches",
            [NO_MATCH, [{"role": "user", "content": "kept"}]],
            None,
            [{"role": "user", "content": "kept"}],
        ),
        (
            "stamps the parent context",
            [[{"role": "assistant (tool result)", "content": "r"}], []],
            EmitSpec(tool_call_id=LiteralExpr(value="parent")),
            [{"role": "assistant (tool result)", "content": "r", "tool_call_id": "parent"}],
        ),
    ]
)
def test_delegate_each(
    _name: str, results: list[DispatchResult], stamp: EmitSpec | None, expected: list[CompatMessage]
) -> None:
    rule = DelegateEachRule(on=ANYTHING, followups=(), source=LiteralExpr(value=["x", "y"]), stamp=stamp)
    assert rule.produce(SCOPE, FakeEngine(results=results), False, 0) == expected


def test_delegate_each_skips_a_non_list_source() -> None:
    engine = FakeEngine()
    rule = DelegateEachRule(on=ANYTHING, followups=(), source=LiteralExpr(value="nope"), stamp=None)
    assert rule.produce(SCOPE, engine, False, 0) == []
    assert engine.dispatched == []
