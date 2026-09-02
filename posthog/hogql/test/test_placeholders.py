from typing import cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.visitor import clear_locations

from common.hogvm.python.utils import HogVMException


class TestParser(BaseTest):
    def test_find_placeholders(self):
        expr = parse_expr("{foo} and {bar.bah}")
        self.assertEqual(sorted(find_placeholders(expr).placeholder_fields), sorted([["foo"], ["bar", "bah"]]))

    def test_find_placeholders_bound_filters_call(self):
        # {filters(...)} must count as filters usage; classifying it as a generic expression
        # placeholder would send it to the Hog VM, which has no `filters` function
        expr = parse_expr("{filters(a AS timestamp, b AS 'plan')} and {foo} and {1 + 2}")
        finder = find_placeholders(expr)
        self.assertTrue(finder.has_filters)
        self.assertEqual(finder.placeholder_fields, [["foo"]])
        self.assertEqual(len(finder.placeholder_expressions), 1)

    def test_find_placeholders_dotted_filters_calls(self):
        # The dotted call forms must count as filters usage too; the Hog VM has no `filters` global.
        # A dotted call on anything else stays an expression placeholder.
        expr = parse_expr("{filters.interval('week')} and {filters.breakdown(a AS 'plan')} and {other.call(1)}")
        finder = find_placeholders(expr)
        self.assertTrue(finder.has_filters)
        self.assertEqual(finder.placeholder_fields, [])
        self.assertEqual(len(finder.placeholder_expressions), 1)

    def test_replace_placeholders_simple(self):
        expr = clear_locations(parse_expr("{foo}"))
        self.assertEqual(
            expr,
            ast.Placeholder(expr=ast.Field(chain=["foo"])),
        )
        expr2 = replace_placeholders(expr, {"foo": ast.Constant(value="bar")})
        self.assertEqual(
            expr2,
            ast.Constant(value="bar"),
        )

    def test_replace_placeholders_error(self):
        expr = ast.Placeholder(expr=ast.Field(chain=["foo"]))
        with self.assertRaises(HogVMException) as context:
            replace_placeholders(expr, {})
        self.assertEqual(
            "Global variable not found: foo",
            str(context.exception),
        )
        with self.assertRaises(HogVMException) as context:
            replace_placeholders(expr, {"bar": ast.Constant(value=123)})
        self.assertEqual(
            "Global variable not found: foo",
            str(context.exception),
        )

    def test_replace_placeholders_comparison(self):
        expr = clear_locations(parse_expr("timestamp < {timestamp}"))
        self.assertEqual(
            expr,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Placeholder(expr=ast.Field(chain=["timestamp"])),
            ),
        )
        expr2 = replace_placeholders(expr, {"timestamp": ast.Constant(value=123)})
        self.assertEqual(
            expr2,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=123),
            ),
        )

    def test_assert_no_placeholders(self):
        expr = ast.Placeholder(expr=ast.Field(chain=["foo"]))
        with self.assertRaises(HogVMException) as context:
            replace_placeholders(expr, None)
        self.assertEqual(
            "Global variable not found: foo",
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


class TestBytecodePlaceholders(BaseTest):
    def _first_select_expr(self, select_query: ast.SelectQuery):
        """Small helper to grab the first expression in the SELECT list."""
        self.assertGreater(len(select_query.select), 0)
        return select_query.select[0]

    def test_numeric_arithmetic_placeholder(self):
        """
        `select {1 + 2}` → constant 3 in the final AST.
        """
        query = cast(ast.SelectQuery, parse_select("SELECT {1 + 2} AS sum"))
        replaced = cast(ast.SelectQuery, replace_placeholders(query, {}))

        first_expr = self._first_select_expr(replaced)
        self.assertIsInstance(first_expr, ast.Alias)
        self.assertIsInstance(first_expr.expr, ast.Constant)
        self.assertEqual(first_expr.expr.value, 3)

        # Finder should report an *expression* placeholder, not a field string.
        finder = find_placeholders(query)
        self.assertTrue(len(finder.placeholder_expressions) > 0)
        self.assertEqual(len(finder.placeholder_fields), 0)

    def test_string_literal_placeholder(self):
        """
        `select {'hello'}` → constant 'hello'.
        """
        query = cast(ast.SelectQuery, parse_select("SELECT {'hello'}"))
        replaced = cast(ast.SelectQuery, replace_placeholders(query, {}))

        first_expr = self._first_select_expr(replaced)
        self.assertIsInstance(first_expr, ast.Constant)
        self.assertEqual(first_expr.value, "hello")

    def test_sql_field_placeholder(self):
        """
        `select {sql(event)}` should yield an AST Field chain ["event"].
        """
        query = cast(
            ast.SelectQuery,
            parse_select("SELECT {sql(event)} FROM events"),
        )
        replaced = cast(ast.SelectQuery, replace_placeholders(query, {}))

        field_expr = self._first_select_expr(replaced)
        self.assertIsInstance(field_expr, ast.Field)
        self.assertEqual(field_expr.chain, ["event"])

    def test_sql_expression_placeholder(self):
        """
        `select {sql(1 + 2)}` stays an AST *expression* (`1 + 2`),
        not a Constant, because sql() returns AST, not a value.
        """
        query = cast(ast.SelectQuery, parse_select("SELECT {sql(1 + 2)}"))
        replaced = cast(ast.SelectQuery, replace_placeholders(query, {}))

        expr = self._first_select_expr(replaced)
        self.assertNotIsInstance(expr, ast.Constant)
        self.assertEqual(to_printed_hogql(expr, team=self.team), "plus(1, 2)")

    def test_immediate_function_placeholder_with_hogqlx(self):
        """
        The complex lambda / JSX example supplied in the prompt should parse
        and substitute to:
          * select[0]  -> HogQLXTag(kind="strong", …)
          * select[1]  -> Constant(2)
          * where      -> Constant(True)
        """

        hogql = """
        SELECT
            {(() -> {
                let a := 'fun';
                return <strong>{sql(event)} ... <blink>{a}</blink></strong>;
            })()},
            {2},
            timestamp
        FROM events
        WHERE {(() -> { return sql(true) })()}
        """

        parsed = cast(ast.SelectQuery, parse_select(hogql))
        replaced = cast(ast.SelectQuery, replace_placeholders(parsed, {}))

        # First SELECT expression: <strong>...</strong>
        first = self._first_select_expr(replaced)
        self.assertIsInstance(first, ast.HogQLXTag)
        self.assertEqual(first.kind, "strong")
        self.assertIsInstance(first.attributes, list)
        self.assertEqual(len(first.attributes), 1)
        elements = first.attributes[0].value
        self.assertEqual(len(elements), 3)
        self.assertIsInstance(elements[0], ast.Field)
        self.assertEqual(elements[0].chain, ["event"])
        self.assertEqual(elements[1], " ... ")
        self.assertIsInstance(elements[2], ast.HogQLXTag)
        self.assertEqual(elements[2].kind, "blink")
        self.assertEqual(elements[2].attributes, [ast.HogQLXAttribute(name="children", value=["fun"])])

        # Second SELECT expression: constant 2
        second = replaced.select[1]
        assert isinstance(second, ast.Constant)
        assert second.value == 2

        # WHERE clause: constant true
        assert isinstance(replaced.where, ast.Constant)
        assert replaced.where.value is True

    def test_find_placeholders_on_expression(self):
        """
        `{1+2}` must be detected as an expression placeholder only.
        """
        expr = parse_expr("{1+2}")
        finder = find_placeholders(expr)
        self.assertTrue(len(finder.placeholder_expressions) > 0)
        self.assertEqual(finder.placeholder_fields, [])

    @parameterized.expand(
        [
            ("sleep_direct", "{sleep(600)}", "sleep"),
            ("run_direct", "{run('SELECT 1')}", "run"),
            ("nested_in_another_call", "{concat(sleep(600))}", "sleep"),
            # Indirect invocations bypass the static name check but must still be rejected at VM
            # dispatch, otherwise the blocking function runs on the request thread.
            ("sleep_expression_call", "{(sleep)(600)}", "sleep"),
            ("run_expression_call", "{(run)('SELECT 1')}", "run"),
            ("sleep_bound_to_local", "{(() -> {let f := sleep; return f(600)})()}", "sleep"),
        ]
    )
    def test_replace_placeholders_rejects_blocking_functions(self, _name, query, fn_name):
        expr = parse_expr(query)
        with self.assertRaises((QueryError, HogVMException)) as context:
            replace_placeholders(expr, {})
        self.assertIn(fn_name, str(context.exception))
