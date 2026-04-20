import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.database.schema.traffic_type import (
    create_bot_name_field,
    create_is_bot_field,
    create_traffic_category_field,
    create_traffic_type_field,
    user_agent_expr,
)

FACTORY_FUNCTIONS = [
    create_is_bot_field,
    create_traffic_type_field,
    create_traffic_category_field,
    create_bot_name_field,
]
FIELD_NAMES = ["$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name"]


class TestUserAgentExpr:
    def test_default_properties_path(self):
        expr = user_agent_expr()
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"
        assert len(expr.args) == 2
        # First arg should be nullIf($raw_user_agent, '') to handle empty strings
        null_if = expr.args[0]
        assert isinstance(null_if, ast.Call)
        assert null_if.name == "nullIf"
        assert null_if.args[0] == ast.Field(chain=["properties", "$raw_user_agent"])
        assert null_if.args[1] == ast.Constant(value="")
        assert expr.args[1] == ast.Field(chain=["properties", "$user_agent"])

    def test_custom_properties_path(self):
        expr = user_agent_expr(properties_path=["poe", "properties"])
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"
        null_if = expr.args[0]
        assert isinstance(null_if, ast.Call)
        assert null_if.name == "nullIf"
        assert null_if.args[0] == ast.Field(chain=["poe", "properties", "$raw_user_agent"])
        assert expr.args[1] == ast.Field(chain=["poe", "properties", "$user_agent"])


class TestExpressionFieldFactories:
    @pytest.mark.parametrize(
        "factory_fn,field_name",
        list(zip(FACTORY_FUNCTIONS, FIELD_NAMES)),
    )
    def test_returns_expression_field_with_correct_name(self, factory_fn, field_name):
        field = factory_fn(name=field_name)
        assert isinstance(field, ExpressionField)
        assert field.name == field_name

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_isolate_scope_is_true(self, factory_fn):
        field = factory_fn(name="test")
        assert field.isolate_scope is True

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_expr_is_not_none(self, factory_fn):
        field = factory_fn(name="test")
        assert field.expr is not None

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_custom_properties_path_propagates(self, factory_fn):
        default_field = factory_fn(name="test")
        custom_field = factory_fn(name="test", properties_path=["poe", "properties"])
        assert default_field.expr != custom_field.expr


class TestIsBotField:
    def test_returns_compare_operation(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert field.expr.op == ast.CompareOperationOp.NotEq

    def test_uses_multiMatchAnyIndex(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert isinstance(field.expr.left, ast.Call)
        assert field.expr.left.name == "multiMatchAnyIndex"

    def test_compares_against_zero(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert isinstance(field.expr.right, ast.Constant)
        assert field.expr.right.value == 0

    def test_wraps_user_agent_in_ifnull(self):
        field = create_is_bot_field(name="$virt_is_bot")
        expr = field.expr
        assert isinstance(expr, ast.CompareOperation)
        index_call = expr.left
        assert isinstance(index_call, ast.Call)
        safe_ua = index_call.args[0]
        assert isinstance(safe_ua, ast.Call)
        assert safe_ua.name == "ifNull"
        coalesce_call = safe_ua.args[0]
        assert isinstance(coalesce_call, ast.Call)
        assert coalesce_call.name == "coalesce"
        # First coalesce arg should be nullIf for empty string handling
        null_if = coalesce_call.args[0]
        assert isinstance(null_if, ast.Call)
        assert null_if.name == "nullIf"


class TestTrafficTypeField:
    def test_returns_if_expression(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_regular(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "Regular"

    def test_labels_contain_expected_values(self):
        expr = create_traffic_type_field(name="$virt_traffic_type").expr
        assert isinstance(expr, ast.Call)
        array_access = expr.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)
        labels = [e.value for e in labels_array.exprs if isinstance(e, ast.Constant)]
        assert "AI Agent" in labels
        assert "Bot" in labels
        assert "Automation" in labels

    def test_uses_multiMatchAnyIndex(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        comparison = field.expr.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"


class TestTrafficCategoryField:
    def test_returns_if_expression(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_regular(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        assert isinstance(field.expr, ast.Call)
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "regular"

    def test_labels_contain_expected_categories(self):
        expr = create_traffic_category_field(name="$virt_traffic_category").expr
        assert isinstance(expr, ast.Call)
        array_access = expr.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)
        labels = [e.value for e in labels_array.exprs if isinstance(e, ast.Constant)]
        assert "ai_crawler" in labels
        assert "ai_search" in labels
        assert "ai_assistant" in labels
        assert "search_crawler" in labels
        assert "seo_crawler" in labels
        assert "social_crawler" in labels
        assert "monitoring" in labels
        assert "http_client" in labels
        assert "headless_browser" in labels
        assert "no_user_agent" in labels


class TestBotNameField:
    def test_returns_if_expression(self):
        field = create_bot_name_field(name="$virt_bot_name")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_empty_string(self):
        field = create_bot_name_field(name="$virt_bot_name")
        assert isinstance(field.expr, ast.Call)
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == ""

    def test_labels_contain_expected_bot_names(self):
        expr = create_bot_name_field(name="$virt_bot_name").expr
        assert isinstance(expr, ast.Call)
        array_access = expr.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)
        labels = [e.value for e in labels_array.exprs if isinstance(e, ast.Constant)]
        assert "Googlebot" in labels
        assert "ChatGPT" in labels
        assert "Claude" in labels
        assert "GPTBot" in labels
        assert "OpenAI Search" in labels
        assert "curl" in labels
        assert "" in labels
