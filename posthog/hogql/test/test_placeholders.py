from typing import cast
from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import replace_placeholders, find_placeholders
from posthog.test.base import BaseTest


class TestParser(BaseTest):
    def test_find_placeholders(self):
        expr = parse_expr("{foo} and {bar}")
        self.assertEqual(sorted(find_placeholders(expr)), sorted(["foo", "bar"]))

    def test_replace_placeholders_simple(self):
        expr = parse_expr("{foo}")
        self.assertEqual(
            expr,
            ast.Placeholder(expr=ast.Field(chain=["foo"], start=0, end=5), start=0, end=5),
        )
        expr2 = replace_placeholders(expr, {"foo": ast.Constant(value="bar")})
        self.assertEqual(
            expr2,
            ast.Constant(value="bar", start=0, end=5),
        )

    def test_replace_placeholders_error(self):
        expr = ast.Placeholder(expr=ast.Field(chain=["foo"]))
        with self.assertRaises(QueryError) as context:
            replace_placeholders(expr, {})
        self.assertEqual(
            "Placeholders, such as {foo}, are not supported in this context",
            str(context.exception),
        )
        with self.assertRaises(QueryError) as context:
            replace_placeholders(expr, {"bar": ast.Constant(value=123)})
        self.assertEqual(
            "Placeholder {foo} is not available in this context. You can use the following: bar",
            str(context.exception),
        )

    def test_replace_placeholders_comparison(self):
        expr = parse_expr("timestamp < {timestamp}")
        self.assertEqual(
            expr,
            ast.CompareOperation(
                start=0,
                end=23,
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"], start=0, end=9),
                right=ast.Placeholder(expr=ast.Field(chain=["timestamp"]), start=12, end=23),
            ),
        )
        expr2 = replace_placeholders(expr, {"timestamp": ast.Constant(value=123)})
        self.assertEqual(
            expr2,
            ast.CompareOperation(
                start=0,
                end=23,
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"], start=0, end=9),
                right=ast.Constant(value=123, start=12, end=23),
            ),
        )

    def test_assert_no_placeholders(self):
        expr = ast.Placeholder(expr=ast.Field(chain=["foo"]))
        with self.assertRaises(QueryError) as context:
            replace_placeholders(expr, None)
        self.assertEqual(
            "Placeholders, such as {foo}, are not supported in this context",
            str(context.exception),
        )

    def test_replace_placeholders_with_cte(self):
        expr = cast(ast.SelectQuery, parse_select("with test as (select {foo}) select * from test"))

        assert expr.ctes is not None and expr.ctes["test"] is not None
        assert isinstance(expr.ctes["test"].expr, ast.SelectQuery)
        assert isinstance(expr.ctes["test"].expr.select[0], ast.Placeholder)

        expr2 = cast(ast.SelectQuery, replace_placeholders(expr, {"foo": ast.Constant(value=1)}))

        assert expr2.ctes is not None and expr2.ctes["test"] is not None
        assert isinstance(expr2.ctes["test"].expr, ast.SelectQuery)
        assert isinstance(expr2.ctes["test"].expr.select[0], ast.Constant)
