from posthog.hogql.hogql import HogQLContext, translate_hogql
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestHogQLContext(APIBaseTest, ClickhouseTestMixin):
    # Helper to always translate HogQL with a blank context
    def _translate(self, query: str):
        return translate_hogql(query, HogQLContext())

    def test_hogql_literals(self):
        self.assertEqual(self._translate("1 + 2"), "plus(1, 2)")
        self.assertEqual(self._translate("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(self._translate("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(self._translate("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(self._translate("1.0 % 2.66"), "modulo(1.0, 2.66)")
        self.assertEqual(translate_hogql("'string'", HogQLContext(values=None)), "'string'")
        self.assertEqual(translate_hogql('"string"', HogQLContext(values=None)), "'string'")
        self.assertEqual(self._translate("'string'"), "%(val_0)s")
        self.assertEqual(self._translate('"string"'), "%(val_0)s")

    def test_hogql_fields_and_properties(self):
        self.assertEqual(
            self._translate("properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate("properties['bla']"),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate('properties["bla"]'),
            "replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate("properties.$bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, '$bla'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate("person.properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(person_properties, 'bla'), '^\"|\"$', '')",
        )
        self.assertEqual(self._translate("uuid"), "uuid")
        self.assertEqual(self._translate("event"), "event")
        self.assertEqual(self._translate("timestamp"), "timestamp")
        self.assertEqual(self._translate("distinct_id"), "distinct_id")
        self.assertEqual(self._translate("person_id"), "person_id")
        self.assertEqual(self._translate("person.created_at"), "person_created_at")

    def test_hogql_materialized_fields_and_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")
        self.assertEqual(self._translate("properties['$browser']"), '"mat_$browser"')

        materialize("events", "$initial_waffle", table_column="person_properties")
        self.assertEqual(self._translate("person.properties['$initial_waffle']"), '"mat_pp_$initial_waffle"')

    def test_hogql_methods(self):
        self.assertEqual(self._translate("count()"), "count(*)")
        self.assertEqual(self._translate("count(event)"), "count(distinct event)")

    def test_hogql_functions(self):
        context = HogQLContext(values=None)  # inline values
        self.assertEqual(self._translate("abs(1)"), "abs(1)")
        self.assertEqual(self._translate("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(translate_hogql("toInt('1')", context), "toInt64OrNull('1')")
        self.assertEqual(translate_hogql("toFloat('1.3')", context), "toFloat64OrNull('1.3')")

    def test_hogql_expr_parse_errors(self):
        self._assert_value_error("", "Module body must contain only one 'Expr'")
        self._assert_value_error("a = 3", "Module body must contain only one 'Expr'")
        self._assert_value_error("(", "SyntaxError: unexpected EOF while parsing")
        self._assert_value_error("())", "SyntaxError: unmatched ')'")
        self._assert_value_error("this makes little sense", "SyntaxError: invalid syntax")
        self._assert_value_error("avg(bla)", "Unknown event field 'bla'")
        self._assert_value_error("count(2,4)", "Aggregation 'count' expects one or zero arguments.")
        self._assert_value_error("avg(2,1)", "Aggregation 'avg' expects just one argument.")
        self._assert_value_error(
            "bla.avg(bla)", "Can only call simple functions like 'avg(properties.bla)' or 'count()'"
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
        context = HogQLContext()
        translate_hogql("avg(properties.prop) + avg(uuid) + event", context)
        self.assertEqual(context.attribute_list, [["properties", "prop"], ["uuid"], ["event"]])
        self.assertEqual(context.found_aggregation, True)

        context = HogQLContext()
        translate_hogql("coalesce(event, properties.event)", context)
        self.assertEqual(context.attribute_list, [["event"], ["properties", "event"]])
        self.assertEqual(context.found_aggregation, False)

        context = HogQLContext()
        translate_hogql("count() + sum(timestamp)", context)
        self.assertEqual(context.attribute_list, [["timestamp"]])
        self.assertEqual(context.found_aggregation, True)

        context = HogQLContext()
        translate_hogql("event + avg(event + properties.event) + avg(event + properties.event)", context)
        self.assertEqual(
            context.attribute_list, [["event"], ["event"], ["properties", "event"], ["event"], ["properties", "event"]]
        )
        self.assertEqual(context.found_aggregation, True)

    def test_hogql_logic(self):
        self.assertEqual(
            self._translate("event or timestamp"),
            "or(event, timestamp)",
        )
        self.assertEqual(
            self._translate("properties.bla and properties.bla2"),
            "and(replaceRegexpAll(JSONExtractRaw(properties, 'bla'), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(properties, 'bla2'), '^\"|\"$', ''))",
        )
        self.assertEqual(
            self._translate("event or timestamp or true or count()"),
            "or(event, timestamp, true, count(*))",
        )
        self.assertEqual(
            self._translate("event or not timestamp"),
            "or(event, not(timestamp))",
        )

    def test_hogql_comparisons(self):
        context = HogQLContext(values=None)  # inline values
        self.assertEqual(translate_hogql("event == 'E'", context), "equals(event, 'E')")
        self.assertEqual(translate_hogql("event != 'E'", context), "notEquals(event, 'E')")
        self.assertEqual(translate_hogql("event > 'E'", context), "greater(event, 'E')")
        self.assertEqual(translate_hogql("event >= 'E'", context), "greaterOrEquals(event, 'E')")
        self.assertEqual(translate_hogql("event < 'E'", context), "less(event, 'E')")
        self.assertEqual(translate_hogql("event <= 'E'", context), "lessOrEquals(event, 'E')")

    def test_hogql_special_root_properties(self):
        self.assertEqual(
            self._translate("*"),
            "tuple(uuid,event,properties,timestamp,team_id,distinct_id,elements_chain,created_at,person_id,person_created_at,person_properties)",
        )
        self.assertEqual(
            self._translate("person"),
            "tuple(distinct_id, person_id, person_created_at, replaceRegexpAll(JSONExtractRaw(person_properties, 'name'), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(person_properties, 'email'), '^\"|\"$', ''))",
        )
        self._assert_value_error("person + 1", 'Can not use the field "person" in an expression')

    def test_hogql_values(self):
        context = HogQLContext()
        self.assertEqual(translate_hogql("event == 'E'", context), "equals(event, %(val_0)s)")
        self.assertEqual(context.values, {"val_0": "E"})
        self.assertEqual(
            translate_hogql("coalesce(4.2, 5, 'lol', 'hoo')", context), "coalesce(4.2, 5, %(val_1)s, %(val_2)s)"
        )
        self.assertEqual(context.values, {"val_0": "E", "val_1": "lol", "val_2": "hoo"})

    def _assert_value_error(self, expr, expected_error):
        with self.assertRaises(ValueError) as context:
            self._translate(expr)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))
