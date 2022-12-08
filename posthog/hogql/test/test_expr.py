from posthog.hogql.expr import hogql_expr_to_clickhouse_expr
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, test_with_materialized_columns


class TestHogQLExpr(ClickhouseTestMixin, APIBaseTest):
    def test_hogql_literals(self):
        self.assertEqual(hogql_expr_to_clickhouse_expr("1 + 2"), "plus(1, 2)")
        self.assertEqual(hogql_expr_to_clickhouse_expr("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(hogql_expr_to_clickhouse_expr("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(hogql_expr_to_clickhouse_expr("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(hogql_expr_to_clickhouse_expr("'string'"), "'string'")
        self.assertEqual(hogql_expr_to_clickhouse_expr('"string"'), "'string'")

    @test_with_materialized_columns(["$browser"])
    def test_hogql_fields_and_properties(self):
        self.assertEqual(
            hogql_expr_to_clickhouse_expr("properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            hogql_expr_to_clickhouse_expr("properties['bla']"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            hogql_expr_to_clickhouse_expr('properties["bla"]'),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        # self.assertEqual(hogql_expr_to_clickhouse_expr("properties['$browser']"), "\"mat_$browser\"")
        self.assertEqual(
            hogql_expr_to_clickhouse_expr("person.properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(person_properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(hogql_expr_to_clickhouse_expr("uuid"), "uuid")
        self.assertEqual(hogql_expr_to_clickhouse_expr("event"), "event")
        self.assertEqual(hogql_expr_to_clickhouse_expr("timestamp"), "timestamp")
        self.assertEqual(hogql_expr_to_clickhouse_expr("distinct_id"), "distinct_id")
        self.assertEqual(hogql_expr_to_clickhouse_expr("person_id"), "person_id")
        self.assertEqual(hogql_expr_to_clickhouse_expr("person.created_at"), "person_created_at")

    def test_hogql_methods(self):
        self.assertEqual(hogql_expr_to_clickhouse_expr("total()"), "count(*)")

    def test_hogql_expr_parse_errors(self):
        self._assert_value_error("", "Module body must contain only one 'Expr'")
        self._assert_value_error("a = 3", "Module body must contain only one 'Expr'")
        self._assert_value_error("(", "SyntaxError: unexpected EOF while parsing")
        self._assert_value_error("())", "SyntaxError: unmatched ')'")
        self._assert_value_error("this makes little sense", "SyntaxError: invalid syntax")
        self._assert_value_error("avg(bla)", "Unknown event field 'bla'")
        self._assert_value_error("total(2)", "Method 'total' does not accept any arguments.")
        self._assert_value_error(
            "bla.avg(bla)", "Can only call simple functions like 'avg(properties.bla)' or 'total()'"
        )
        self._assert_value_error("hamburger(bla)", "Unsupported function call 'hamburger(...)'")
        self._assert_value_error("mad(bla)", "Unsupported function call 'mad(...)'")
        self._assert_value_error("yeet.the.cloud", "Unsupported property access: ['yeet', 'the', 'cloud']")
        self._assert_value_error("['properties']['value']", "Unknown node in field access chain:")
        self._assert_value_error("chipotle", "Unknown event field 'chipotle'")
        self._assert_value_error("person.chipotle", "Unknown person field 'chipotle'")

        # TODO
        # self._assert_value_error("avg(avg(2))", "No nested averages")
        # self._assert_value_error("avg(2)", "Averages must be on properties")

    def _assert_value_error(self, expr, expected_error):
        with self.assertRaises(ValueError) as context:
            hogql_expr_to_clickhouse_expr(expr)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))
