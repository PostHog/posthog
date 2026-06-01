import pytest

from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import (
    get_bot_name,
    get_bot_operator,
    get_bot_type,
    get_traffic_category,
    get_traffic_type,
    is_bot,
)

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS


def _ua() -> ast.Field:
    return ast.Field(chain=["properties", "$user_agent"])


def _unwrap_udf(call: ast.Call) -> tuple[str, ast.Expr]:
    """Unpack (udf_name, ifNull(ua, '') inner expr) from a wrapped UDF call."""
    assert isinstance(call, ast.Call)
    assert len(call.args) == 1
    ifnull_call = call.args[0]
    assert isinstance(ifnull_call, ast.Call) and ifnull_call.name == "ifNull"
    assert len(ifnull_call.args) == 2
    assert isinstance(ifnull_call.args[1], ast.Constant) and ifnull_call.args[1].value == ""
    return call.name, ifnull_call.args[0]


class TestTrafficTypeFunctions:
    def test_get_traffic_type_calls_botTrafficType(self):
        result = get_traffic_type(node=ast.Call(name="__preview_getTrafficType", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == "botTrafficType"

    def test_get_traffic_category_calls_botCategory(self):
        result = get_traffic_category(node=ast.Call(name="__preview_getTrafficCategory", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == "botCategory"

    def test_get_bot_name_calls_botName(self):
        result = get_bot_name(node=ast.Call(name="__preview_getBotName", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == "botName"

    def test_get_bot_operator_calls_botOperator(self):
        result = get_bot_operator(node=ast.Call(name="__preview_getBotOperator", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == "botOperator"

    def test_is_bot_calls_isBot(self):
        result = is_bot(node=ast.Call(name="__preview_isBot", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == "isBot"

    def test_get_bot_type_translates_regular_to_empty_string(self):
        # __preview_getBotType returns '' for regular traffic (backwards-compat shape);
        # botCategory defaults to 'regular', so we wrap with if(cat = 'regular', '', cat).
        result = get_bot_type(node=ast.Call(name="__preview_getBotType", args=[]), args=[_ua()])
        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        # condition: equals(botCategory(ifNull(ua, '')), 'regular')
        condition = result.args[0]
        assert isinstance(condition, ast.CompareOperation)
        assert condition.op == ast.CompareOperationOp.Eq
        assert isinstance(condition.left, ast.Call) and condition.left.name == "botCategory"
        assert isinstance(condition.right, ast.Constant) and condition.right.value == "regular"
        # then '': true branch is the empty string
        assert isinstance(result.args[1], ast.Constant) and result.args[1].value == ""
        # else: fall back to the original botCategory call
        assert isinstance(result.args[2], ast.Call) and result.args[2].name == "botCategory"

    def test_null_user_agent_wrapped_in_ifnull(self):
        custom_ua = ast.Field(chain=["custom", "ua"])
        result = get_traffic_type(node=ast.Call(name="__preview_getTrafficType", args=[]), args=[custom_ua])
        _, inner = _unwrap_udf(result)
        assert inner == custom_ua

    @pytest.mark.parametrize(
        "function_builder,expected_udf",
        [
            (get_traffic_type, "botTrafficType"),
            (get_traffic_category, "botCategory"),
            (get_bot_name, "botName"),
            (get_bot_operator, "botOperator"),
            (is_bot, "isBot"),
        ],
    )
    def test_all_simple_functions_use_their_udf(self, function_builder, expected_udf):
        result = function_builder(node=ast.Call(name="test", args=[]), args=[_ua()])
        udf_name, _ = _unwrap_udf(result)
        assert udf_name == expected_udf


class TestBotDefinitionsDataStructure:
    """Data-integrity tests that don't depend on AST structure."""

    def test_all_bot_definitions_have_required_fields(self):
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.name, f"Bot definition for {pattern} missing name"
            assert bot_def.category, f"Bot definition for {pattern} missing category"
            assert bot_def.traffic_type, f"Bot definition for {pattern} missing traffic_type"
            assert bot_def.operator, f"Bot definition for {pattern} missing operator"

    def test_traffic_types_are_valid(self):
        valid_types = {"AI Agent", "Bot", "Automation"}
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.traffic_type in valid_types, f"Invalid traffic_type for {pattern}: {bot_def.traffic_type}"

    def test_longer_patterns_come_before_shorter_substrings(self):
        patterns = list(BOT_DEFINITIONS.keys())
        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns):
                if i != j and p1 in p2 and len(p1) < len(p2):
                    assert patterns.index(p2) < patterns.index(p1), (
                        f"{p2} must come before {p1} to avoid ambiguity in REGEXP_TREE matching"
                    )
