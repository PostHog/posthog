import json
from pathlib import Path

import pytest

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer import normalizer as normalizer_module
from products.ai_observability.backend.logic.message_normalizer.compiler import compile_recipe
from products.ai_observability.backend.logic.message_normalizer.errors import RecipeRuntimeError, RecipeTimeoutError
from products.ai_observability.backend.logic.message_normalizer.normalizer import (
    DEFAULT_RECIPE_FILES,
    DEFAULT_RECIPES_DIR,
    RecipeNormalizer,
    StoredRecipe,
    default_recipes,
    merge_recipes,
)
from products.ai_observability.backend.logic.message_normalizer.pipeline import RunOutcome
from products.ai_observability.backend.logic.message_normalizer.rules import Recipe
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, CompatMessage, JsonValue, Value

TS_DEFAULT_RECIPES = Path(__file__).parents[6] / "packages/llm-normalizer/src/normalizer/recipe/default_recipes"
ECHO = compile_recipe({"id": "echo", "rules": [{"on": {"say": {"exists": True}}, "emit": {"content": "$.say"}}]})


def test_bundled_recipes_are_byte_identical_to_the_typescript_ones() -> None:
    ours = sorted(path.name for path in DEFAULT_RECIPES_DIR.glob("*.yaml"))
    assert ours == sorted(path.name for path in TS_DEFAULT_RECIPES.glob("*.yaml"))
    assert ours == sorted(f"{name}.yaml" for name in DEFAULT_RECIPE_FILES)
    for name in ours:
        assert (DEFAULT_RECIPES_DIR / name).read_bytes() == (TS_DEFAULT_RECIPES / name).read_bytes()


def test_reads_bundled_recipes_as_utf8(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in DEFAULT_RECIPE_FILES:
        text = (DEFAULT_RECIPES_DIR / f"{name}.yaml").read_text(encoding="utf-8")
        (tmp_path / f"{name}.yaml").write_text(text + "# é\n", encoding="utf-8")
    original_read_text = Path.read_text

    def read_text_with_ascii_default(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        return original_read_text(self, encoding=encoding or "ascii", errors=errors)

    monkeypatch.setattr(normalizer_module, "DEFAULT_RECIPES_DIR", tmp_path)
    monkeypatch.setattr(Path, "read_text", read_text_with_ascii_default)
    assert len(default_recipes.__wrapped__()) == len(DEFAULT_RECIPE_FILES)


def test_bundled_recipes_load_with_unique_ids() -> None:
    ids = [recipe.id for recipe in default_recipes()]
    assert len(ids) == len(DEFAULT_RECIPE_FILES) and all(ids)
    assert len(set(ids)) == len(ids)


@parameterized.expand(
    [
        ("a matched input", {"say": "hi"}, RunOutcome(messages=[{"role": "user", "content": "hi"}], recognized=True)),
        ("a missing input", MISSING, RunOutcome(messages=[], recognized=True)),
        (
            "an unmatched input",
            {"weird": 1},
            RunOutcome(messages=[{"role": "user", "content": '{"weird":1}'}], recognized=False),
        ),
    ]
)
def test_normalize_message(_name: str, value: Value, expected: RunOutcome) -> None:
    assert RecipeNormalizer([ECHO]).normalize_message(value, "user") == expected


TOOLS_MESSAGE = {"role": "available tools", "content": "", "tools": [{"name": "search"}]}


@parameterized.expand(
    [
        (
            "prepends the tools message",
            {"say": "hi"},
            [{"name": "search"}],
            [TOOLS_MESSAGE, {"role": "user", "content": "hi"}],
            True,
        ),
        (
            "an empty tools list still adds it",
            None,
            [],
            [{"role": "available tools", "content": "", "tools": []}],
            True,
        ),
        ("empty-string tools add nothing", None, "", [], True),
        ("a scalar input carries no message", 42, MISSING, [], True),
        ("null input carries no message", None, MISSING, [], True),
        (
            "recognition comes from the input",
            {"weird": 1},
            MISSING,
            [{"role": "user", "content": '{"weird":1}'}],
            False,
        ),
    ]
)
def test_normalize_messages(
    _name: str, value: Value, tools: Value, messages: list[CompatMessage], recognized: bool
) -> None:
    assert RecipeNormalizer([ECHO]).normalize_messages(value, "user", tools) == RunOutcome(
        messages=messages, recognized=recognized
    )


def test_merge_returns_the_built_ins_in_order_then_team_recipes_by_database_id() -> None:
    builtin_ids = [recipe.id for recipe in default_recipes()]
    assert [recipe.id for recipe in merge_recipes([])] == builtin_ids
    merged = merge_recipes(
        [
            StoredRecipe(id="db-first", source="rules: []\n"),
            StoredRecipe(id="db-second", source="id: ignored\nrules: []\n"),
        ]
    )
    assert [recipe.id for recipe in merged] == [*builtin_ids, "db-first", "db-second"]


def test_merge_skips_broken_team_recipes_and_keeps_the_rest() -> None:
    good = StoredRecipe(
        id="good", source="rules:\n  - on: {weird_payload: {exists: true}}\n    emit: {content: $.weird_payload}\n"
    )
    date_keyed = StoredRecipe(
        id="date-keyed", source="rules:\n  - on: {2024-01-01: {exists: true}}\n    emit: {content: dated}\n"
    )
    broken = [
        StoredRecipe(id="duplicate-key", source="rules: []\nrules: []\n"),
        StoredRecipe(id="bad-rules", source="rules: 3\n"),
        StoredRecipe(id="bad-yaml", source="not: [valid"),
        StoredRecipe(id="oversized-integer", source="n: " + "9" * 5000 + "\nrules: []\n"),
        StoredRecipe(id="unhashable-key", source="? [[a]]\n: 1\nrules: []\n"),
    ]
    recipes = merge_recipes([*broken, date_keyed, good])
    assert [recipe.id for recipe in recipes] == [*(recipe.id for recipe in default_recipes()), "date-keyed", "good"]
    assert RecipeNormalizer(recipes).normalize_messages({"weird_payload": "hi"}, "user") == RunOutcome(
        messages=[{"role": "user", "content": "hi"}], recognized=True
    )


def test_output_never_carries_the_missing_sentinel() -> None:
    recipe = compile_recipe(
        {"id": "r", "rules": [{"on": {}, "emit": {"spread": {"a": "$.nope", "b": ["$.nope"]}, "content": "x"}}]}
    )
    outcome = RecipeNormalizer([recipe]).normalize_message({}, "user")
    json.dumps(outcome.messages)
    assert outcome.messages == [{"role": "user", "content": "x", "b": [None]}]


def deeply_nested() -> JsonValue:
    value: JsonValue = "leaf"
    for _ in range(100_000):
        value = [value]
    return value


@parameterized.expand(
    [("in the input", {"unknown": deeply_nested()}, MISSING), ("in the tools", "hi", deeply_nested())]
)
def test_deep_nesting_raises_a_runtime_error(_name: str, value: Value, tools: Value) -> None:
    with pytest.raises(RecipeRuntimeError):
        RecipeNormalizer().normalize_messages(value, "user", tools)


SLOW_EXPRESSION = compile_recipe(
    {"id": "slow-expression", "rules": [{"on": {}, "emit": {"content": [{"stringify": "$"}] * 1_000}}]}
)
SLOW_PREDICATE = compile_recipe(
    {"id": "slow-predicate", "rules": [{"on": {"items": {"every": {"in": list(range(20_000))}}}, "emit": {}}]}
)


@parameterized.expand(
    [
        ("in one expression", SLOW_EXPRESSION, {"rows": [{"n": n, "text": "row"} for n in range(5_000)]}),
        # The last item fails the pattern, so no expression runs and only the predicate can see the time limit.
        ("in one predicate", SLOW_PREDICATE, {"items": [*[19_999] * 1_000, "miss"]}),
    ]
)
def test_a_slow_recipe_stops_at_the_time_limit(_name: str, recipe: Recipe, value: Value) -> None:
    with pytest.raises(RecipeTimeoutError):
        RecipeNormalizer([recipe], time_limit_seconds=0.05).normalize_messages(value, "user")
