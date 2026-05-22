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


def _ua() -> ast.Field:
    return ast.Field(chain=["properties", "$user_agent"])


def _dictGetOrDefault_args(call: ast.Call) -> tuple[str, str, ast.Expr, str]:
    """Unpack (dict_name, attribute, ua_expr, default) from a dictGetOrDefault call."""
    assert call.name == "dictGetOrDefault"
    assert len(call.args) == 4
    dict_name = call.args[0]
    attribute = call.args[1]
    ua_expr = call.args[2]
    default = call.args[3]
    assert isinstance(dict_name, ast.Constant)
    assert isinstance(attribute, ast.Constant)
    assert isinstance(ua_expr, ast.Call) and ua_expr.name == "ifNull"
    assert isinstance(default, ast.Constant)
    return dict_name.value, attribute.value, ua_expr, default.value


class TestTrafficTypeFunctions:
    def test_get_traffic_type_returns_dictGetOrDefault(self):
        result = get_traffic_type(node=ast.Call(name="__preview_getTrafficType", args=[]), args=[_ua()])

        assert isinstance(result, ast.Call)
        dict_name, attr, _, default = _dictGetOrDefault_args(result)
        assert "web_bot_definition_dict" in dict_name
        assert attr == "traffic_type"
        assert default == "Regular"

    def test_get_traffic_category_returns_dictGetOrDefault(self):
        result = get_traffic_category(node=ast.Call(name="__preview_getTrafficCategory", args=[]), args=[_ua()])

        assert isinstance(result, ast.Call)
        dict_name, attr, _, default = _dictGetOrDefault_args(result)
        assert "web_bot_definition_dict" in dict_name
        assert attr == "category"
        assert default == "regular"

    def test_get_bot_name_returns_dictGetOrDefault(self):
        result = get_bot_name(node=ast.Call(name="__preview_getBotName", args=[]), args=[_ua()])

        assert isinstance(result, ast.Call)
        dict_name, attr, _, default = _dictGetOrDefault_args(result)
        assert "web_bot_definition_dict" in dict_name
        assert attr == "name"
        assert default == ""

    def test_get_bot_operator_returns_dictGetOrDefault(self):
        result = get_bot_operator(node=ast.Call(name="__preview_getBotOperator", args=[]), args=[_ua()])

        assert isinstance(result, ast.Call)
        dict_name, attr, _, default = _dictGetOrDefault_args(result)
        assert "web_bot_definition_dict" in dict_name
        assert attr == "operator"
        assert default == ""

    def test_get_bot_type_default_is_empty_string(self):
        result = get_bot_type(node=ast.Call(name="__preview_getBotType", args=[]), args=[_ua()])

        assert isinstance(result, ast.Call)
        _, _, _, default = _dictGetOrDefault_args(result)
        assert default == ""

    def test_is_bot_returns_notequals_regular(self):
        result = is_bot(node=ast.Call(name="__preview_isBot", args=[]), args=[_ua()])

        assert isinstance(result, ast.CompareOperation)
        assert result.op == ast.CompareOperationOp.NotEq
        assert isinstance(result.left, ast.Call)
        _dictGetOrDefault_args(result.left)  # validates structure
        assert isinstance(result.right, ast.Constant)
        assert result.right.value == "Regular"

    def test_null_user_agent_wrapped_in_ifnull(self):
        custom_ua = ast.Field(chain=["custom", "ua"])
        result = get_traffic_type(node=ast.Call(name="__preview_getTrafficType", args=[]), args=[custom_ua])

        assert isinstance(result, ast.Call)
        assert result.name == "dictGetOrDefault"
        ifnull_call = result.args[2]
        assert isinstance(ifnull_call, ast.Call)
        assert ifnull_call.name == "ifNull"
        assert ifnull_call.args[0] == custom_ua
        assert isinstance(ifnull_call.args[1], ast.Constant)
        assert ifnull_call.args[1].value == ""

    @pytest.mark.parametrize(
        "function_builder,expected_attr,expected_default",
        [
            (get_traffic_type, "traffic_type", "Regular"),
            (get_traffic_category, "category", "regular"),
            (get_bot_type, "category", ""),
            (get_bot_name, "name", ""),
            (get_bot_operator, "operator", ""),
        ],
    )
    def test_all_functions_use_web_bot_definition_dict(self, function_builder, expected_attr, expected_default):
        result = function_builder(node=ast.Call(name="test", args=[]), args=[_ua()])
        assert isinstance(result, ast.Call)
        dict_name, attr, _, default = _dictGetOrDefault_args(result)
        assert "web_bot_definition_dict" in dict_name
        assert attr == expected_attr
        assert default == expected_default


class TestBotDefinitionsDataStructure:
    """Keep the data-integrity tests here since they don't depend on AST structure."""

    from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS as _BOT_DEFINITIONS

    def test_all_bot_definitions_have_required_fields(self):
        from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.name, f"Bot definition for {pattern} missing name"
            assert bot_def.category, f"Bot definition for {pattern} missing category"
            assert bot_def.traffic_type, f"Bot definition for {pattern} missing traffic_type"
            assert bot_def.operator, f"Bot definition for {pattern} missing operator"

    def test_traffic_types_are_valid(self):
        from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

        valid_types = {"AI Agent", "Bot", "Automation"}
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.traffic_type in valid_types, f"Invalid traffic_type for {pattern}: {bot_def.traffic_type}"

    def test_longer_patterns_come_before_shorter_substrings(self):
        from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

        patterns = list(BOT_DEFINITIONS.keys())
        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns):
                if i != j and p1 in p2 and len(p1) < len(p2):
                    assert patterns.index(p2) < patterns.index(p1), (
                        f"{p2} must come before {p1} to avoid ambiguity in REGEXP_TREE matching"
                    )
