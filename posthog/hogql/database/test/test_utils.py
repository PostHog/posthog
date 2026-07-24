from unittest import TestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.utils import get_join_field_chain, qualify_join_key_expr


class TestJoinKeyExtraction(TestCase):
    @parameterized.expand(
        [
            ("plain_field", "distinct_id", ["distinct_id"]),
            ("nested_field", "properties.merchant_domain", ["properties", "merchant_domain"]),
            ("call_first_arg", "toString(distinct_id)", ["distinct_id"]),
            # Regression: the join field isn't the first argument of the call.
            (
                "if_field_in_second_arg",
                "if(event = 'SaveProduct', properties.merchant_domain, NULL)",
                ["properties", "merchant_domain"],
            ),
            ("coalesce_field_after_call", "coalesce(toString(properties.a), properties.b)", ["properties", "a"]),
        ]
    )
    def test_get_join_field_chain(self, _name: str, key: str, expected: list[str]) -> None:
        self.assertEqual(get_join_field_chain(key), expected)

    def test_get_join_field_chain_returns_none_without_field(self) -> None:
        self.assertIsNone(get_join_field_chain("1 + 2"))

    @parameterized.expand(
        [
            ("plain_field", "distinct_id", ["events", "distinct_id"]),
            ("call_first_arg", "toString(distinct_id)", ["events", "distinct_id"]),
        ]
    )
    def test_qualify_join_key_expr_prefixes_field(self, _name: str, key: str, expected_chain: list[str]) -> None:
        expr = qualify_join_key_expr(key, "events")
        assert expr is not None
        self.assertEqual(_first_field(expr).chain, expected_chain)

    def test_qualify_conditional_key_prefixes_value_field(self) -> None:
        # Regression: qualify the value field, not the condition in the first argument.
        expr = qualify_join_key_expr("if(event = 'SaveProduct', properties.merchant_domain, NULL)", "events")
        assert isinstance(expr, ast.Call)
        value_field = expr.args[1]
        assert isinstance(value_field, ast.Field)
        self.assertEqual(value_field.chain, ["events", "properties", "merchant_domain"])


def _first_field(expr: ast.Expr) -> ast.Field:
    if isinstance(expr, ast.Field):
        return expr
    if isinstance(expr, ast.Call):
        for arg in expr.args:
            if isinstance(arg, ast.Field):
                return arg
    raise AssertionError(f"No field found in {expr}")
