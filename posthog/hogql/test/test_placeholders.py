from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.placeholders import replace_placeholders
from posthog.test.base import BaseTest


class TestParser(BaseTest):
    def test_replace_placeholders_simple(self):
        expr = parse_expr("{foo}")
        self.assertEqual(
            expr,
            ast.Placeholder(field="foo"),
        )
        expr2 = replace_placeholders(expr, {"foo": ast.Constant(value="bar")})
        self.assertEqual(
            expr2,
            ast.Constant(value="bar"),
        )

    def test_replace_placeholders_comparison(self):
        expr = parse_expr("timestamp < {timestamp}")
        self.assertEqual(
            expr,
            ast.CompareOperation(
                op=ast.CompareOperationType.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Placeholder(field="timestamp"),
            ),
        )
        expr2 = replace_placeholders(expr, {"timestamp": ast.Constant(value=123)})
        self.assertEqual(
            expr2,
            ast.CompareOperation(
                op=ast.CompareOperationType.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=123),
            ),
        )
