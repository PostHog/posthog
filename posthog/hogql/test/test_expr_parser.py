from typing import Any, Dict

from posthog.hogql.expr_parser import ExprParserContext, translate_hql
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestExprParser(APIBaseTest, ClickhouseTestMixin):
    def test_hogql_literals(self):
        self.assertEqual(translate_hql("1 + 2"), "plus(1, 2)")
        self.assertEqual(translate_hql("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(translate_hql("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(translate_hql("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(translate_hql("1.0 % 2.66"), "modulo(1.0, 2.66)")
        self.assertEqual(translate_hql("'string'"), "'string'")
        self.assertEqual(translate_hql('"string"'), "'string'")

    def test_hogql_fields_and_properties(self):
        self.assertEqual(
            translate_hql("properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            translate_hql("properties['bla']"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            translate_hql('properties["bla"]'),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            translate_hql("properties.$bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, '$bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            translate_hql("person.properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(person_properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(translate_hql("uuid"), "uuid")
        self.assertEqual(translate_hql("event"), "event")
        self.assertEqual(translate_hql("timestamp"), "timestamp")
        self.assertEqual(translate_hql("distinct_id"), "distinct_id")
        self.assertEqual(translate_hql("person_id"), "person_id")
        self.assertEqual(translate_hql("person.created_at"), "person_created_at")

    def test_hogql_materialized_fields_and_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")
        self.assertEqual(translate_hql("properties['$browser']"), '"mat_$browser"')

        materialize("events", "$initial_waffle", table_column="person_properties")
        self.assertEqual(translate_hql("person.properties['$initial_waffle']"), '"mat_pp_$initial_waffle"')

    def test_hogql_methods(self):
        self.assertEqual(translate_hql("total()"), "count(*)")

    def test_hogql_functions(self):
        self.assertEqual(translate_hql("abs(1)"), "abs(1)")
        self.assertEqual(translate_hql("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(translate_hql("toInt('1')"), "toInt64OrNull('1')")
        self.assertEqual(translate_hql("toFloat('1.3')"), "toFloat64OrNull('1.3')")

    def test_hogql_expr_parse_errors(self):
        self._assert_value_error("", "Module body must contain only one 'Expr'")
        self._assert_value_error("a = 3", "Module body must contain only one 'Expr'")
        self._assert_value_error("(", "SyntaxError: unexpected EOF while parsing")
        self._assert_value_error("())", "SyntaxError: unmatched ')'")
        self._assert_value_error("this makes little sense", "SyntaxError: invalid syntax")
        self._assert_value_error("avg(bla)", "Unknown event field 'bla'")
        self._assert_value_error("total(2)", "Aggregation 'total' does not accept any arguments.")
        self._assert_value_error("avg(2,1)", "Aggregation 'avg' expects just one argument.")
        self._assert_value_error(
            "bla.avg(bla)", "Can only call simple functions like 'avg(properties.bla)' or 'total()'"
        )
        self._assert_value_error("hamburger(bla)", "Unsupported function call 'hamburger(...)'")
        self._assert_value_error("mad(bla)", "Unsupported function call 'mad(...)'")
        self._assert_value_error("yeet.the.cloud", "Unsupported property access: ['yeet', 'the', 'cloud']")
        self._assert_value_error("['properties']['value']", "Unknown node in field access chain:")
        self._assert_value_error("['properties']['value']['bla']", "Unknown node in field access chain:")
        self._assert_value_error("chipotle", "Unknown event field 'chipotle'")
        self._assert_value_error("person.chipotle", "Unknown person field 'chipotle'")
        self._assert_value_error("avg(2)", "avg(...) must be called on fields or properties, not literals.")
        self._assert_value_error(
            "avg(avg(properties.bla))", "Aggregation 'avg' cannot be nested inside another aggregation 'avg'."
        )
        self._assert_value_error("1;2", "Module body must contain only one 'Expr'")

    def test_hogql_returned_properties(self):
        context = ExprParserContext()
        translate_hql("avg(properties.prop) + avg(uuid) + event", context)
        self.assertEqual(context.attribute_list, [["properties", "prop"], ["uuid"], ["event"]])
        self.assertEqual(context.is_aggregation, True)

        context = ExprParserContext()
        translate_hql("coalesce(event, properties.event)", context)
        self.assertEqual(context.attribute_list, [["event"], ["properties", "event"]])
        self.assertEqual(context.is_aggregation, False)

        context = ExprParserContext()
        translate_hql("total() + sum(timestamp)", context)
        self.assertEqual(context.attribute_list, [["timestamp"]])
        self.assertEqual(context.is_aggregation, True)

        context = ExprParserContext()
        translate_hql("event + avg(event + properties.event) + avg(event + properties.event)", context)
        self.assertEqual(
            context.attribute_list, [["event"], ["event"], ["properties", "event"], ["event"], ["properties", "event"]]
        )
        self.assertEqual(context.is_aggregation, True)

    def test_hogql_logic(self):
        self.assertEqual(
            translate_hql("event or timestamp"),
            "or(event, timestamp)",
        )
        self.assertEqual(
            translate_hql("properties.bla and properties.bla2"),
            "and(replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(properties, 'bla2'), '^\"|\"$', ''))",
        )
        self.assertEqual(
            translate_hql("event or timestamp or true or total()"),
            "or(event, timestamp, true, count(*))",
        )
        self.assertEqual(
            translate_hql("event or not timestamp"),
            "or(event, not(timestamp))",
        )

    def test_hogql_comparisons(self):
        self.assertEqual(translate_hql("event == 'E'"), "equals(event, 'E')")
        self.assertEqual(translate_hql("event != 'E'"), "notEquals(event, 'E')")
        self.assertEqual(translate_hql("event > 'E'"), "greater(event, 'E')")
        self.assertEqual(translate_hql("event >= 'E'"), "greaterOrEquals(event, 'E')")
        self.assertEqual(translate_hql("event < 'E'"), "less(event, 'E')")
        self.assertEqual(translate_hql("event <= 'E'"), "lessOrEquals(event, 'E')")

    def test_hogql_special_root_properties(self):
        self.assertEqual(
            translate_hql("*"),
            "tuple(uuid,event,properties,timestamp,team_id,distinct_id,elements_chain,created_at,person_id,person_created_at,person_properties)",
        )
        self.assertEqual(
            translate_hql("person"),
            "tuple(distinct_id, person_id, person_created_at, replaceRegexpAll(JSONExtractRaw(person_properties, 'name'), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(person_properties, 'email'), '^\"|\"$', ''))",
        )
        self._assert_value_error("person + 1", 'Can not use the field "person" in an expression')

    def test_collected_values(self):
        collected_values: Dict[str, Any] = {}
        context = ExprParserContext(collect_values=collected_values)
        self.assertEqual(translate_hql("event == 'E'", context), "equals(event, %(val_0)s)")
        self.assertEqual(collected_values, {"val_0": "E"})
        self.assertEqual(
            translate_hql("coalesce(4.2, 5, 'lol', 'hoo')", context), "coalesce(4.2, 5, %(val_1)s, %(val_2)s)"
        )
        self.assertEqual(collected_values, {"val_0": "E", "val_1": "lol", "val_2": "hoo"})

    def _assert_value_error(self, expr, expected_error):
        with self.assertRaises(ValueError) as context:
            translate_hql(expr)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))
