import pytest

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.compiler import compile_recipe, nearest_operator
from products.ai_observability.backend.logic.message_normalizer.errors import RecipeCompileError
from products.ai_observability.backend.logic.message_normalizer.expressions import InterpExpr, PathExpr
from products.ai_observability.backend.logic.message_normalizer.rules import DelegateRule, EmitRule, Rule
from products.ai_observability.backend.logic.message_normalizer.scope import Scope
from products.ai_observability.backend.logic.message_normalizer.values import Value
from products.ai_observability.backend.logic.message_normalizer.yaml_loader import load_recipe_yaml

SCOPE = Scope.for_node({"name": "Ada", "items": ["a", "b"]}, "user")
OPERATORS = ("select", "reject", "coalesce", "join", "omit", "stringify", "literal")


def only_rule(raw: object) -> Rule:
    return compile_recipe({"id": "t", "rules": [raw]}).rules[0]


def emitted(slot: str, raw_value: object) -> Value:
    rule = only_rule({"on": {}, "emit": {slot: raw_value}})
    assert isinstance(rule, EmitRule)
    expr = getattr(rule.emit, slot)
    return expr.eval(SCOPE)


def test_compiles_a_recipe_into_rules() -> None:
    recipe = compile_recipe(
        {"id": "greet", "rules": [{"on": {}, "emit": {"content": "hi"}}, {"on": {}, "delegate": "$"}]}
    )
    assert recipe.id == "greet"
    assert [type(rule) for rule in recipe.rules] == [EmitRule, DelegateRule]


def test_the_fallback_id_names_a_recipe_without_one() -> None:
    assert compile_recipe({"rules": []}, "stored-id").id == "stored-id"


@parameterized.expand(
    [
        ("a field read", "$.name", "Ada"),
        ("the whole input", "$", {"name": "Ada", "items": ["a", "b"]}),
        ("an interpolation", "hello $.name!", "hello Ada!"),
        ("a dollar in plain text", "costs $5", "costs $5"),
        ("a one-key operator", {"join": {"from": "$.items", "sep": ","}}, "a,b"),
        ("an object of values", {"who": "$.name", "n": 1}, {"who": "Ada", "n": 1}),
        ("a literal escaping an operator name", {"literal": {"join": "x"}}, {"join": "x"}),
        ("a coalesce over a list", {"coalesce": ["$.missing", "$.name"]}, "Ada"),
        ("a select with a bare pluck field", {"select": {"from": [{"t": 1}, {"t": 2}], "pluck": "t"}}, [1, 2]),
    ]
)
def test_compiles_values(_name: str, raw_value: object, expected: Value) -> None:
    assert emitted("content", raw_value) == expected


def test_a_date_literal_compiles_to_its_text_as_the_frontend_parser_reads_it() -> None:
    raw = load_recipe_yaml("id: t\nrules:\n  - on: {}\n    emit: {content: 2026-10-28}\n")
    rule = compile_recipe(raw).rules[0]
    assert isinstance(rule, EmitRule) and rule.emit.content is not None
    assert rule.emit.content.eval(SCOPE) == "2026-10-28"


def test_a_bare_scalar_field_compiles_to_an_equality_predicate() -> None:
    rule = only_rule({"on": {"type": "reasoning"}, "emit": {}})
    assert rule.on.matches({"type": "reasoning"})
    assert not rule.on.matches({"type": "text"})


def test_non_ascii_path_names_compile_like_javascript() -> None:
    rule = only_rule({"on": {}, "emit": {"content": "$.héllo"}})
    assert isinstance(rule, EmitRule)
    assert rule.emit.content == InterpExpr(parts=(PathExpr(segments=("h",)), "éllo"))


@parameterized.expand(
    [
        (
            "an operator with the wrong payload",
            {"id": "t", "rules": [{"on": {}, "emit": {"content": {"join": "x"}}}]},
            "takes a mapping",
        ),
        (
            "a misspelt operator",
            {"id": "t", "rules": [{"on": {}, "emit": {"content": {"jon": {"from": "$.items"}}}}]},
            "Did you mean 'join'",
        ),
        ("a rootless field", {"id": "t", "rules": [{"on": {}, "emit": {"content": "$name"}}]}, "Use '\\$.name'"),
        ("a rule with no action", {"id": "t", "rules": [{"on": {}}]}, "emit, delegate, delegateEach"),
        ("a missing id", {"rules": []}, "missing an 'id'"),
        ("a missing rules sequence", {"id": "t"}, "missing a 'rules:'"),
        ("a non-mapping recipe", ["rules"], "mapping at top level"),
        (
            "a predicate with two verbs",
            {"id": "t", "rules": [{"on": {"f": {"equals": 1, "exists": True}}, "emit": {}}]},
            "multiple verbs",
        ),
        (
            "an unknown emit key",
            {"id": "t", "rules": [{"on": {}, "emit": {"colour": "red"}}]},
            "Unknown emit key 'colour'",
        ),
        ("a bad type name", {"id": "t", "rules": [{"on": {"f": {"is": "text"}}, "emit": {}}]}, "'is:' must be a type"),
        (
            "a bad type name in a list",
            {"id": "t", "rules": [{"on": {"f": {"is": ["string", "text"]}}, "emit": {}}]},
            "'is:' must be a type or array of types, got \"text\"$",
        ),
    ]
)
def test_rejects_invalid_recipes(_name: str, raw: object, message: str) -> None:
    with pytest.raises(RecipeCompileError, match=message):
        compile_recipe(raw)


def test_prefixes_rule_errors_with_the_recipe_and_rule() -> None:
    with pytest.raises(RecipeCompileError, match=r"^Recipe 't' rule\[1\]: "):
        compile_recipe({"id": "t", "rules": [{"on": {}, "emit": {}}, {"on": "nope", "emit": {}}]})


@parameterized.expand([("selct", "select"), ("joins", "join"), ("omat", "omit")])
def test_suggests_the_nearest_operator(typo: str, expected: str) -> None:
    assert nearest_operator(typo, OPERATORS) == expected


@parameterized.expand([("completely_different",), ("select",)])
def test_suggests_nothing_for_a_distant_or_exact_name(key: str) -> None:
    assert nearest_operator(key, OPERATORS) is None
