import json
import tracemalloc
from pathlib import Path
from typing import Final

import pytest

import structlog
from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer import (
    normalizer as normalizer_module,
    run_limits as run_limits_module,
)
from products.ai_observability.backend.logic.message_normalizer.compiler import compile_recipe
from products.ai_observability.backend.logic.message_normalizer.errors import (
    RecipeOutputLimitError,
    RecipeRuntimeError,
    RecipeTimeoutError,
)
from products.ai_observability.backend.logic.message_normalizer.normalizer import (
    DEFAULT_RECIPE_FILES,
    DEFAULT_RECIPES_DIR,
    RecipeNormalizer,
    StoredRecipe,
    compile_stored_recipe,
    default_recipes,
    merge_recipes,
)
from products.ai_observability.backend.logic.message_normalizer.pipeline import RunOutcome
from products.ai_observability.backend.logic.message_normalizer.rules import Recipe
from products.ai_observability.backend.logic.message_normalizer.run_limits import check_time_limit, time_limit
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, CompatMessage, JsonValue, Value

ECHO = compile_recipe({"id": "echo", "rules": [{"on": {"say": {"exists": True}}, "emit": {"content": "$.say"}}]})


def test_every_bundled_recipe_file_is_registered() -> None:
    ours = sorted(path.name for path in DEFAULT_RECIPES_DIR.glob("*.yaml"))
    assert ours == sorted(f"{name}.yaml" for name in DEFAULT_RECIPE_FILES)


def test_a_run_reports_every_recipe_that_matched_including_nested_dispatches() -> None:
    outcome = RecipeNormalizer([*default_recipes(), ECHO]).normalize_messages([{"say": "hi"}], "user")

    assert "echo" in outcome.matched_recipe_ids
    assert outcome.matched_recipe_ids - {"echo"}, "the built-in that split the list is reported too"


def test_a_run_logs_non_text_content_once_with_a_count_per_type() -> None:
    each_as_content = compile_recipe(
        {
            "id": "each-as-content",
            "rules": [
                {"on": {"items": {"is": "array"}}, "delegateEach": "$.items"},
                {"on": {"k": {"exists": True}}, "emit": {"content": "$"}},
            ],
        }
    )

    with structlog.testing.capture_logs() as logs:
        RecipeNormalizer([each_as_content]).normalize_messages({"items": [{"k": 1}, {"k": 2}, {"k": 3}]}, "user")

    assert [(log["event"], log["content_types"]) for log in logs] == [
        ("llma_recipe_produced_non_text_content", {"object": 3})
    ]


def test_normalizing_if_matched_never_serializes_an_unmatched_value() -> None:
    too_deep_to_serialize: dict = {}
    cursor = too_deep_to_serialize
    for _ in range(100_000):
        cursor["a"] = {}
        cursor = cursor["a"]
    normalizer = RecipeNormalizer([*default_recipes(), ECHO])

    with pytest.raises(RecipeRuntimeError):
        normalizer.normalize_messages(too_deep_to_serialize, "user")
    assert normalizer.normalize_if_matched(too_deep_to_serialize, "user", frozenset({"echo"})) is None


def test_normalizing_if_matched_runs_a_recipe_once_when_nothing_needs_a_fallback() -> None:
    normalizer = RecipeNormalizer([*default_recipes(), ECHO])

    with structlog.testing.capture_logs() as logs:
        outcome = normalizer.normalize_if_matched({"say": {"not": "text"}}, "user", frozenset({"echo"}))

    assert outcome == RunOutcome(messages=({"role": "user", "content": ""},), recognized=True)
    assert [log["event"] for log in logs] == ["llma_recipe_produced_non_text_content"]


def test_normalizing_if_matched_falls_back_for_items_no_recipe_matched() -> None:
    outcome = RecipeNormalizer([*default_recipes(), ECHO]).normalize_if_matched(
        [{"say": "hi"}, {"weird": 1}], "user", frozenset({"echo"})
    )

    assert outcome is not None
    assert [message["content"] for message in outcome.messages] == ["hi", '{"weird":1}']


def test_custom_recipe_ids_leave_out_the_bundled_recipes() -> None:
    assert RecipeNormalizer([*default_recipes(), ECHO]).custom_recipe_ids == frozenset({"echo"})
    assert RecipeNormalizer().custom_recipe_ids == frozenset()


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
        ("a matched input", {"say": "hi"}, RunOutcome(messages=({"role": "user", "content": "hi"},), recognized=True)),
        ("a missing input", MISSING, RunOutcome(messages=(), recognized=True)),
        (
            "an unmatched input",
            {"weird": 1},
            RunOutcome(messages=({"role": "user", "content": '{"weird":1}'},), recognized=False),
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
        messages=tuple(messages), recognized=recognized
    )


def compiled(stored: list[StoredRecipe]) -> list[Recipe]:
    return [recipe for recipe in map(compile_stored_recipe, stored) if recipe is not None]


def test_merge_returns_the_built_ins_in_order_then_team_recipes_by_database_id() -> None:
    builtin_ids = [recipe.id for recipe in default_recipes()]
    assert [recipe.id for recipe in merge_recipes([])] == builtin_ids
    merged = merge_recipes(
        compiled(
            [
                StoredRecipe(id="db-first", source="rules: []\n"),
                StoredRecipe(id="db-second", source="id: ignored\nrules: []\n"),
            ]
        )
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
    with structlog.testing.capture_logs() as logs:
        recipes = merge_recipes(compiled([*broken, date_keyed, good]))
    assert [(log["event"], log["recipe_id"], log["error_type"]) for log in logs] == [
        ("llma_team_recipe_skipped", "duplicate-key", "DuplicateKeyError"),
        ("llma_team_recipe_skipped", "bad-rules", "RecipeCompileError"),
        ("llma_team_recipe_skipped", "bad-yaml", "ParserError"),
        ("llma_team_recipe_skipped", "oversized-integer", "ValueError"),
        ("llma_team_recipe_skipped", "unhashable-key", "TypeError"),
    ]
    assert [recipe.id for recipe in recipes] == [*(recipe.id for recipe in default_recipes()), "date-keyed", "good"]
    assert RecipeNormalizer(recipes).normalize_messages({"weird_payload": "hi"}, "user") == RunOutcome(
        messages=({"role": "user", "content": "hi"},), recognized=True
    )


def test_output_never_carries_the_missing_sentinel() -> None:
    recipe = compile_recipe(
        {"id": "r", "rules": [{"on": {}, "emit": {"spread": {"a": "$.nope", "b": ["$.nope"]}, "content": "x"}}]}
    )
    outcome = RecipeNormalizer([recipe]).normalize_message({}, "user")
    json.dumps(outcome.messages)
    assert outcome.messages == ({"role": "user", "content": "x", "b": [None]},)


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


def fan_out(depth: int) -> Recipe:
    # Each level hands down eight references to the same node, so the value serializes to 8^depth copies of the event.
    delegations = [{"on": {f"l{k}": {"exists": True}}, "delegate": {f"l{k + 1}": ["$"] * 8}} for k in range(depth)]
    emit = {"on": {f"l{depth}": {"exists": True}}, "emit": {"content": {"stringify": "$"}}}
    return compile_recipe({"id": "fan-out", "rules": [*delegations, emit]})


def aliased_refs() -> Recipe:
    tens = ["$"] * 10
    thousand = [[tens] * 10] * 10
    return compile_recipe(
        {"id": "aliased", "rules": [{"on": {}, "emit": {"content": {"stringify": {"all": thousand}}}}]}
    )


SLOW_EXPRESSION = compile_recipe(
    {"id": "slow-expression", "rules": [{"on": {}, "emit": {"content": [{"stringify": "$"}] * 1_000}}]}
)
SLOW_PREDICATE = compile_recipe(
    {"id": "slow-predicate", "rules": [{"on": {"items": {"every": {"in": list(range(20_000))}}}, "emit": {}}]}
)
# The last item fails the pattern, so no expression runs and only the predicate can see the time limit.
SLOW_PREDICATE_INPUT: Value = {"items": [*[19_999] * 1_000, "miss"]}
# Every candidate has the length of the input and differs only in its last character, so each comparison scans it all.
SLOW_MEMBERSHIP = compile_recipe(
    {"id": "slow-membership", "rules": [{"on": {"text": {"in": ["a" * 100_000 + "b"] * 50_000}}, "emit": {}}]}
)
# Every call's arguments are the same text, which never parses and so is never charged. Only the parse can see the
# time limit.
FAILED_PARSES = compile_recipe(
    {
        "id": "failed-parses",
        "rules": [
            {
                "on": {},
                "emit": {
                    "content": "",
                    "toolCalls": [{"type": "function", "function": {"name": "f", "arguments": "$.big"}}] * 200,
                },
            }
        ],
    }
)


@parameterized.expand(
    [
        ("in one expression", SLOW_EXPRESSION, {"rows": [{"n": n, "text": "row"} for n in range(5_000)]}),
        ("in one predicate", SLOW_PREDICATE, SLOW_PREDICATE_INPUT),
        ("in one membership scan", SLOW_MEMBERSHIP, {"text": "a" * 100_000 + "c"}),
        # The value is built in a few evaluations, so only the serialization walk can see the time limit.
        ("in one serialization", fan_out(6), {"l0": 1}),
        ("in failed parses", FAILED_PARSES, {"big": "[" + "0," * 500_000}),
    ]
)
def test_a_slow_recipe_stops_at_the_time_limit(_name: str, recipe: Recipe, value: Value) -> None:
    with pytest.raises(RecipeTimeoutError):
        RecipeNormalizer([recipe], time_limit_seconds=0.05).normalize_messages(value, "user")


def test_a_pattern_keyed_by_an_index_matches_a_list_like_the_typescript_engine() -> None:
    recipe = compile_recipe(
        {
            "id": "first",
            "rules": [{"on": {"$": {"is": "array"}, "0": {"is": "string"}}, "emit": {"content": "matched"}}],
        }
    )
    assert RecipeNormalizer([recipe]).normalize_message(["a", "b"], "user") == RunOutcome(
        messages=({"role": "user", "content": "matched"},), recognized=True
    )


def test_an_outer_time_limit_wins_over_a_later_run_deadline() -> None:
    with time_limit(0.05), pytest.raises(RecipeTimeoutError, match=r"\(0\.05s\)"):
        RecipeNormalizer([SLOW_PREDICATE], time_limit_seconds=60).normalize_messages(SLOW_PREDICATE_INPUT, "user")


@pytest.fixture
def low_output_char_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_limits_module, "MAX_OUTPUT_CHARS", 1_000_000)


@pytest.fixture
def low_output_node_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_limits_module, "MAX_OUTPUT_NODES", 10_000)


def peak_memory_of_a_failed_run(recipe: Recipe, value: Value, match: str) -> int:
    normalizer = RecipeNormalizer([recipe], time_limit_seconds=0.5)
    tracemalloc.start()
    try:
        with pytest.raises(RecipeOutputLimitError, match=match):
            normalizer.normalize_message(value, "user")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


@pytest.mark.parametrize(
    "recipe, value",
    [
        pytest.param(fan_out(4), {"l0": "x" * 1_000}, id="delegate fan-out"),
        pytest.param(aliased_refs(), {"text": "x" * 2_000}, id="aliased $ refs"),
        pytest.param(
            compile_recipe(
                {
                    "id": "salvage",
                    "rules": [{"on": {"big": {"exists": True}}, "delegateEach": [{"content": "$.big"}] * 1_000}],
                }
            ),
            {"big": "x" * 2_000},
            id="salvaged text",
        ),
        pytest.param(
            compile_recipe(
                {
                    "id": "stamp",
                    "rules": [
                        {"on": {"id": {"exists": True}}, "delegateEach": "$.blocks", "stamp": {"toolCallId": "$.id"}}
                    ],
                }
            ),
            {"id": "x" * 2_000, "blocks": [""] * 1_000},
            id="stamped tool call ids",
        ),
        pytest.param(
            compile_recipe(
                {"id": "salvage", "rules": [{"on": {"blocks": {"exists": True}}, "delegateEach": "$.blocks"}]}
            ),
            {"role": "x" * 2_000, "blocks": [""] * 1_000},
            id="salvaged inherited roles",
        ),
        pytest.param(
            compile_recipe(
                {
                    "id": "stamp",
                    "rules": [
                        {"on": {"blocks": {"exists": True}}, "delegateEach": "$.blocks", "stamp": {"role": "$.missing"}}
                    ],
                }
            ),
            {"role": "x" * 2_000, "blocks": [{"role": "user"}] * 1_000},
            id="stamped inherited roles",
        ),
    ],
)
@pytest.mark.usefixtures("low_output_char_cap")
def test_oversized_output_stops_at_the_output_budget(recipe: Recipe, value: Value) -> None:
    with pytest.raises(RecipeOutputLimitError, match="characters"):
        RecipeNormalizer([recipe], time_limit_seconds=0.05).normalize_message(value, "user")


@pytest.mark.parametrize(
    "value, tools",
    [
        pytest.param(MISSING, [{"name": "t"}] * 6_000, id="tools alone"),
        pytest.param({"say": ["x"] * 2_000}, [{"name": "t"}] * 3_000, id="tools and messages share one budget"),
    ],
)
@pytest.mark.usefixtures("low_output_node_cap")
def test_copying_the_tools_charges_the_output_budget(value: Value, tools: Value) -> None:
    with pytest.raises(RecipeOutputLimitError, match="values"):
        RecipeNormalizer([ECHO]).normalize_messages(value, "user", tools)


@pytest.mark.usefixtures("low_output_node_cap")
def test_a_fan_out_of_small_values_stops_at_the_output_node_budget() -> None:
    with pytest.raises(RecipeOutputLimitError, match="values"):
        RecipeNormalizer([fan_out(6)], time_limit_seconds=0.05).normalize_message({"l0": 1}, "user")


def emit_content(content: object) -> Recipe:
    return compile_recipe({"id": "content", "rules": [{"on": {}, "emit": {"content": content}}]})


def nested_join(source: object, innermost_sep: object) -> object:
    joined = innermost_sep
    for _ in range(3):
        joined = {"join": {"from": source, "sep": joined}}
    return joined


@pytest.mark.parametrize(
    "recipe, value",
    [
        pytest.param(
            emit_content(nested_join("$.items", "$.text")), {"items": [""] * 300, "text": "x"}, id="from event data"
        ),
        pytest.param(emit_content(nested_join([""] * 300, "x")), {}, id="from literals"),
    ],
)
@pytest.mark.usefixtures("low_output_char_cap")
def test_nested_joins_stop_at_the_output_budget_before_building_the_text(recipe: Recipe, value: Value) -> None:
    # Each level repeats the previous level's text between 300 items, so the outer join would hold about 27M characters.
    assert peak_memory_of_a_failed_run(recipe, value, "characters") < 1_000_000


@pytest.mark.usefixtures("low_output_char_cap")
def test_serializing_text_charges_its_escapes_before_writing_them() -> None:
    # The joins build about 330k control characters, which json.dumps writes as `\u0000`, six times as long.
    recipe = emit_content({"stringify": {"text": nested_join([""] * 70, "\x00")}})
    assert peak_memory_of_a_failed_run(recipe, {}, "characters") < 1_000_000


@pytest.mark.parametrize(
    "per_item, item",
    [
        pytest.param({"select": {"from": {"literal": [0] * 1_000}}}, 0, id="select"),
        pytest.param({"reject": {"from": {"literal": [0] * 1_000}}}, 0, id="reject"),
        pytest.param({"omit": {"from": {"literal": {str(n): n for n in range(1_000)}}}}, 0, id="omit"),
    ],
)
@pytest.mark.usefixtures("low_output_node_cap")
def test_a_copy_per_item_stops_at_the_output_budget_before_copying(per_item: object, item: Value) -> None:
    # Each of 1,000 items gets its own 1,000-value copy, so the result would hold a million values.
    recipe = emit_content({"select": {"from": "$.items", "pluck": per_item}})
    assert peak_memory_of_a_failed_run(recipe, {"items": [item] * 1_000}, "values") < 1_000_000


@pytest.mark.parametrize(
    "emit, item, cap, match",
    [
        pytest.param(
            {"content": {"select": {"from": "$.items", "pluck": {"try_parse_structured_content": "$"}}}},
            json.dumps([{"type": "text"}] * 100),
            ("MAX_OUTPUT_CHARS", 20_000),
            "characters",
            id="content blocks charged by their text",
        ),
        pytest.param(
            {"content": "", "toolCalls": "$.items"},
            {"type": "function", "id": "c1", "function": {"name": "f", "arguments": json.dumps([[]] * 100)}},
            ("MAX_OUTPUT_NODES", 5_000),
            "values",
            id="tool call arguments charged by their values",
        ),
    ],
)
def test_a_kept_parse_per_item_stops_at_the_output_budget(
    monkeypatch: pytest.MonkeyPatch, emit: object, item: Value, cap: tuple[str, int], match: str
) -> None:
    # Each of 1,000 items keeps its own parse of the same 100-value text, so the result would hold 100k parsed values.
    monkeypatch.setattr(run_limits_module, *cap)
    recipe = compile_recipe({"id": "parse", "rules": [{"on": {}, "emit": emit}]})
    assert peak_memory_of_a_failed_run(recipe, {"items": [item] * 1_000}, match) < 1_000_000


CSV_TEXT = "1234,user1234,user1234@example.com,55.21,active\n" * 4_000
FLAT_RECORDS = json.dumps([{"id": n, "name": f"user{n}", "amount": n * 1.5, "active": True} for n in range(5_000)])
NESTED_RECORDS = json.dumps([{"id": n, "tags": ["a", "b"], "meta": {"k": n}} for n in range(3_000)])
ESCAPED_RECORDS = json.dumps([{"id": n, "text": 'say "hi"\nthen leave', "ok": True} for n in range(3_000)])
PYTHON_REPR_RECORDS = str([{"id": n, "tags": ["a", "b"]} for n in range(3_000)])


def tool_message(content: str) -> CompatMessage:
    return {"role": "tool", "tool_call_id": "c1", "content": content}


def tool_call_message(arguments: JsonValue) -> CompatMessage:
    call: JsonValue = {"type": "function", "id": "c1", "function": {"name": "save", "arguments": arguments}}
    return {"role": "assistant", "tool_calls": [call], "content": ""}


TEXT_MESSAGES: Final = {
    "JSON number array as text": [tool_message(json.dumps([n / 7 for n in range(20_000)]))],
    "JSON record array as text": [tool_message(FLAT_RECORDS)],
    "nested records as text": [tool_message(NESTED_RECORDS)],
    "escaped records as text": [tool_message(ESCAPED_RECORDS)],
    "Python repr records as text": [tool_message(PYTHON_REPR_RECORDS)],
    "text starting with a bracket": [{"role": "user", "content": f"[{CSV_TEXT}"}],
    "text starting with a bracket and a brace": [{"role": "user", "content": f"[{{{CSV_TEXT}"}],
}


@pytest.mark.parametrize(
    "messages, expected",
    [
        pytest.param(
            [tool_call_message(json.dumps({"csv": CSV_TEXT}))],
            [tool_call_message({"csv": CSV_TEXT})],
            id="CSV in tool call arguments",
        ),
        *(pytest.param(messages, messages, id=name) for name, messages in TEXT_MESSAGES.items()),
    ],
)
@pytest.mark.usefixtures("low_output_node_cap", "low_output_char_cap")
def test_large_json_like_text_fits_the_output_budget(
    messages: list[CompatMessage], expected: list[CompatMessage]
) -> None:
    # Each text holds more commas or JSON values than the lowered node cap, and none of it is kept as parsed values.
    assert RecipeNormalizer().normalize_messages(messages, "user") == RunOutcome(
        messages=tuple(expected), recognized=True
    )


UNTERMINATED_ESCAPES = '\\"' * 16_000


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([tool_message(f'[{{"{UNTERMINATED_ESCAPES}')], id="tool content"),
        pytest.param([tool_call_message(f'{{"a"{UNTERMINATED_ESCAPES}')], id="tool call arguments"),
    ],
)
def test_text_that_is_almost_json_is_kept_within_the_time_limit(messages: list[CompatMessage]) -> None:
    # A scan that backtracks over each escaped quote is quadratic in this text and runs in C, where no clock check can
    # stop it. The run must still finish inside a limit that the scan would overrun many times over.
    with time_limit(1.0):
        outcome = RecipeNormalizer().normalize_messages(messages, "user")
        check_time_limit()
    assert outcome == RunOutcome(messages=tuple(messages), recognized=True)


@pytest.mark.parametrize(
    "cap, rule, message",
    [
        pytest.param(
            "MAX_OPERATIONS",
            {"on": {"items": {"exists": True}}, "delegateEach": "$.items"},
            "operation budget",
            id="a delegateEach over many items",
        ),
        pytest.param(
            "MAX_MESSAGES",
            {"on": {}, "emit": {"content": "x"}, "followups": [{"from": "$.items", "each": {"content": "$"}}]},
            "message budget",
            id="an expansion over many items",
        ),
    ],
)
def test_a_run_charges_the_execution_budget(
    monkeypatch: pytest.MonkeyPatch, cap: str, rule: dict[str, object], message: str
) -> None:
    monkeypatch.setattr(run_limits_module, cap, 100)
    recipe = compile_recipe({"id": "runaway", "rules": [rule]})
    with pytest.raises(RecipeRuntimeError, match=message):
        RecipeNormalizer([recipe]).normalize_message({"items": ["a"] * 200}, "user")


def test_large_inline_media_fits_the_output_budget() -> None:
    data = "A" * 20_000_000
    image: Value = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
    outcome = RecipeNormalizer().normalize_message(image, "user")
    # Compared through a flag, because pytest would otherwise diff two 20 MB strings when the assertion fails.
    rendered_in_full = outcome.messages == (
        {"role": "user", "content": [{"type": "image", "image": f"data:image/png;base64,{data}"}]},
    )
    assert outcome.recognized and rendered_in_full
