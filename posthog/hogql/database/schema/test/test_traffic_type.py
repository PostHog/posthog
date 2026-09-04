import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.database.schema.traffic_type import (
    client_ip_expr,
    create_bot_name_field,
    create_bot_operator_field,
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
        # Raw-only on purpose: a $user_agent fallback would force a properties-blob read
        assert user_agent_expr() == ast.Field(chain=["properties", "$raw_user_agent"])

    def test_custom_properties_path(self):
        expr = user_agent_expr(properties_path=["poe", "properties"])
        assert expr == ast.Field(chain=["poe", "properties", "$raw_user_agent"])


class TestClientIPExpr:
    def test_default_properties_path(self):
        assert client_ip_expr() == ast.Field(chain=["properties", "$ip"])

    def test_custom_properties_path(self):
        assert client_ip_expr(["poe", "properties"]) == ast.Field(chain=["poe", "properties", "$ip"])


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


# Each field creator emits a single bot/traffic-type marker call, expanded to the classification SQL in
# the resolver. These assert the field emits the right marker over its user-agent expression; the
# expansion structure (multiMatchAnyIndex, labels, defaults) is covered in test_traffic_type_functions.py.
FIELD_MARKERS = [
    (create_is_bot_field, "$virt_is_bot", "isLikelyBot"),
    (create_traffic_type_field, "$virt_traffic_type", "getTrafficType"),
    (create_traffic_category_field, "$virt_traffic_category", "getTrafficCategory"),
    (create_bot_name_field, "$virt_bot_name", "getBotName"),
    (create_bot_operator_field, "$virt_bot_operator", "getBotOperator"),
]


class TestFieldMarkers:
    @pytest.mark.parametrize("factory_fn,field_name,marker", FIELD_MARKERS)
    def test_emits_marker_over_user_agent_and_ip(self, factory_fn, field_name, marker):
        field = factory_fn(name=field_name)
        marker_call = field.expr.args[2]
        assert isinstance(marker_call, ast.Call)
        assert marker_call.name == marker
        assert marker_call.args == [user_agent_expr(), client_ip_expr()]

    @pytest.mark.parametrize("factory_fn,field_name,marker", FIELD_MARKERS)
    def test_marker_respects_custom_properties_path(self, factory_fn, field_name, marker):
        field = factory_fn(name=field_name, properties_path=["poe", "properties"])
        marker_call = field.expr.args[2]
        assert isinstance(marker_call, ast.Call)
        assert marker_call.name == marker
        assert marker_call.args == [user_agent_expr(["poe", "properties"]), client_ip_expr(["poe", "properties"])]


# $cookieless_mode events always came from a real browser (a cookieless event with no user
# agent is dropped at ingestion instead), so classification must skip the bot heuristics for
# them entirely rather than reach the empty-UA fallback, which defaults to Automation/bot.
COOKIELESS_OVERRIDES = [
    (create_is_bot_field, "$virt_is_bot", False),
    (create_traffic_type_field, "$virt_traffic_type", "Regular"),
    (create_traffic_category_field, "$virt_traffic_category", "regular"),
    (create_bot_name_field, "$virt_bot_name", ""),
    (create_bot_operator_field, "$virt_bot_operator", ""),
]


class TestCookielessOverride:
    @pytest.mark.parametrize("factory_fn,field_name,regular_value", COOKIELESS_OVERRIDES)
    def test_short_circuits_to_the_regular_value_for_cookieless_events(self, factory_fn, field_name, regular_value):
        field = factory_fn(name=field_name)
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"
        condition, when_cookieless, when_not = field.expr.args
        assert isinstance(condition, ast.CompareOperation)
        assert condition.op == ast.CompareOperationOp.Eq
        assert condition.right == ast.Constant(value=True)
        assert when_cookieless == ast.Constant(value=regular_value)
        assert isinstance(when_not, ast.Call)

    @pytest.mark.parametrize("factory_fn,field_name,regular_value", COOKIELESS_OVERRIDES)
    def test_condition_reads_cookieless_mode_and_treats_missing_as_false(self, factory_fn, field_name, regular_value):
        field = factory_fn(name=field_name)
        condition = field.expr.args[0]
        ifnull_call = condition.left
        assert isinstance(ifnull_call, ast.Call)
        assert ifnull_call.name == "ifNull"
        assert ifnull_call.args[0] == ast.Field(chain=["properties", "$cookieless_mode"])
        assert ifnull_call.args[1] == ast.Constant(value=False)

    @pytest.mark.parametrize("factory_fn,field_name,regular_value", COOKIELESS_OVERRIDES)
    def test_condition_respects_custom_properties_path(self, factory_fn, field_name, regular_value):
        field = factory_fn(name=field_name, properties_path=["poe", "properties"])
        ifnull_call = field.expr.args[0].left
        assert ifnull_call.args[0] == ast.Field(chain=["poe", "properties", "$cookieless_mode"])
