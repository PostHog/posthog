import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.database.schema.traffic_type import (
    create_log_bot_name_field,
    create_log_bot_operator_field,
    create_log_is_bot_field,
    create_log_traffic_category_field,
    create_log_traffic_type_field,
    log_user_agent_expr,
)

LOG_FACTORY_FUNCTIONS = [
    create_log_is_bot_field,
    create_log_traffic_type_field,
    create_log_traffic_category_field,
    create_log_bot_name_field,
    create_log_bot_operator_field,
]
LOG_FIELD_NAMES = [
    "$virt_is_bot",
    "$virt_traffic_type",
    "$virt_traffic_category",
    "$virt_bot_name",
    "$virt_bot_operator",
]


class TestLogUserAgentExpr:
    def test_returns_coalesce(self):
        expr = log_user_agent_expr()
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"
        assert len(expr.args) == 4

    def test_checks_otel_http_user_agent_first(self):
        expr = log_user_agent_expr()
        assert isinstance(expr, ast.Call)
        first_null_if = expr.args[0]
        assert isinstance(first_null_if, ast.Call)
        assert first_null_if.name == "nullIf"
        assert first_null_if.args[0] == ast.Field(chain=["attributes", "http.user_agent"])

    def test_checks_user_agent_original_second(self):
        expr = log_user_agent_expr()
        assert isinstance(expr, ast.Call)
        second_null_if = expr.args[1]
        assert isinstance(second_null_if, ast.Call)
        assert second_null_if.name == "nullIf"
        assert second_null_if.args[0] == ast.Field(chain=["attributes", "user_agent.original"])

    def test_checks_posthog_raw_user_agent_third(self):
        expr = log_user_agent_expr()
        assert isinstance(expr, ast.Call)
        third_null_if = expr.args[2]
        assert isinstance(third_null_if, ast.Call)
        assert third_null_if.name == "nullIf"
        assert third_null_if.args[0] == ast.Field(chain=["attributes", "$raw_user_agent"])

    def test_falls_back_to_posthog_user_agent(self):
        expr = log_user_agent_expr()
        assert isinstance(expr, ast.Call)
        assert expr.args[3] == ast.Field(chain=["attributes", "$user_agent"])


class TestLogExpressionFieldFactories:
    @pytest.mark.parametrize(
        "factory_fn,field_name",
        list(zip(LOG_FACTORY_FUNCTIONS, LOG_FIELD_NAMES)),
    )
    def test_returns_expression_field_with_correct_name(self, factory_fn, field_name):
        field = factory_fn(name=field_name)
        assert isinstance(field, ExpressionField)
        assert field.name == field_name

    @pytest.mark.parametrize("factory_fn", LOG_FACTORY_FUNCTIONS)
    def test_isolate_scope_is_true(self, factory_fn):
        field = factory_fn(name="test")
        assert field.isolate_scope is True

    @pytest.mark.parametrize("factory_fn", LOG_FACTORY_FUNCTIONS)
    def test_expr_uses_log_attributes(self, factory_fn):
        field = factory_fn(name="test")
        expr_str = str(field.expr)
        assert "attributes" in expr_str


class TestLogIsBotField:
    def test_returns_compare_operation(self):
        field = create_log_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert field.expr.op == ast.CompareOperationOp.NotEq

    def test_uses_multiMatchAnyIndex(self):
        field = create_log_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert isinstance(field.expr.left, ast.Call)
        assert field.expr.left.name == "multiMatchAnyIndex"


class TestLogTrafficTypeField:
    def test_returns_if_expression(self):
        field = create_log_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_regular(self):
        field = create_log_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "Regular"
