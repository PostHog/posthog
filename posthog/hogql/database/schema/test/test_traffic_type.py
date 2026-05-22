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


def _unwrap_dictGetOrDefault(expr: ast.Expr) -> tuple[str, str, str]:
    """Return (dict_name, attribute, default) from a dictGetOrDefault call."""
    assert isinstance(expr, ast.Call)
    assert expr.name == "dictGetOrDefault"
    assert len(expr.args) == 4
    dict_name = expr.args[0]
    attribute = expr.args[1]
    default = expr.args[3]
    assert isinstance(dict_name, ast.Constant)
    assert isinstance(attribute, ast.Constant)
    assert isinstance(default, ast.Constant)
    return dict_name.value, attribute.value, default.value


class TestIsBotField:
    def test_returns_compare_operation(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert field.expr.op == ast.CompareOperationOp.NotEq

    def test_uses_dictGetOrDefault(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert isinstance(field.expr.left, ast.Call)
        assert field.expr.left.name == "dictGetOrDefault"

    def test_compares_against_regular(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        assert isinstance(field.expr.right, ast.Constant)
        assert field.expr.right.value == "Regular"

    def test_dict_lookup_uses_traffic_type_attribute(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.CompareOperation)
        _, attribute, default = _unwrap_dictGetOrDefault(field.expr.left)
        assert attribute == "traffic_type"
        assert default == "Regular"


class TestTrafficTypeField:
    def test_returns_dictGetOrDefault(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "dictGetOrDefault"

    def test_default_value_is_regular(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        _, attribute, default = _unwrap_dictGetOrDefault(field.expr)
        assert attribute == "traffic_type"
        assert default == "Regular"


class TestTrafficCategoryField:
    def test_returns_dictGetOrDefault(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "dictGetOrDefault"

    def test_default_value_is_regular(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        _, attribute, default = _unwrap_dictGetOrDefault(field.expr)
        assert attribute == "category"
        assert default == "regular"


class TestBotNameField:
    def test_returns_dictGetOrDefault(self):
        field = create_bot_name_field(name="$virt_bot_name")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "dictGetOrDefault"

    def test_default_value_is_empty_string(self):
        field = create_bot_name_field(name="$virt_bot_name")
        _, attribute, default = _unwrap_dictGetOrDefault(field.expr)
        assert attribute == "name"
        assert default == ""
