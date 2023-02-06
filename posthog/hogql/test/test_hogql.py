from typing import Optional

from django.test.testcases import TestCase

from posthog.hogql.context import HogQLContext, HogQLFieldAccess
from posthog.hogql.hogql import translate_hogql


class TestHogQLContext(TestCase):
    # Helper to always translate HogQL with a blank context
    def _translate(self, query: str, context: Optional[HogQLContext] = None) -> str:
        return translate_hogql(query, context or HogQLContext())

    def test_hogql_literals(self):
        self.assertEqual(self._translate("1 + 2"), "plus(1, 2)")
        self.assertEqual(self._translate("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(self._translate("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(self._translate("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(self._translate("1.0 % 2.66"), "modulo(1.0, 2.66)")
        self.assertEqual(self._translate("'string'"), "%(hogql_val_0)s")
        self.assertEqual(self._translate('"string"'), "%(hogql_val_0)s")

    def test_hogql_equals_null(self):
        self.assertEqual(self._translate("1 == null"), "isNull(1)")
        self.assertEqual(self._translate("1 != null"), "isNotNull(1)")

    def test_hogql_fields_and_properties(self):
        self.assertEqual(
            self._translate("properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate("properties['bla']"),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._translate('properties["bla"]'),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )

        context = HogQLContext()
        self.assertEqual(
            self._translate("properties.$bla", context),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        self.assertEqual(
            context.field_access_logs,
            [
                HogQLFieldAccess(
                    ["properties", "$bla"],
                    "event.properties",
                    "$bla",
                    "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
                )
            ],
        )

        context = HogQLContext()
        self.assertEqual(
            self._translate("person.properties.bla", context),
            "replaceRegexpAll(JSONExtractRaw(person_properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        self.assertEqual(
            context.field_access_logs,
            [
                HogQLFieldAccess(
                    ["person", "properties", "bla"],
                    "person.properties",
                    "bla",
                    "replaceRegexpAll(JSONExtractRaw(person_properties, %(hogql_val_0)s), '^\"|\"$', '')",
                )
            ],
        )

        context = HogQLContext()
        self.assertEqual(self._translate("uuid", context), "uuid")
        self.assertEqual(context.field_access_logs, [HogQLFieldAccess(["uuid"], "event", "uuid", "uuid")])

        context = HogQLContext()
        self.assertEqual(self._translate("event", context), "event")
        self.assertEqual(context.field_access_logs, [HogQLFieldAccess(["event"], "event", "event", "event")])

        context = HogQLContext()
        self.assertEqual(self._translate("timestamp", context), "timestamp")
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["timestamp"], "event", "timestamp", "timestamp")]
        )

        context = HogQLContext()
        self.assertEqual(self._translate("distinct_id", context), "distinct_id")
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["distinct_id"], "event", "distinct_id", "distinct_id")]
        )

        context = HogQLContext()
        self.assertEqual(self._translate("person_id", context), "person_id")
        self.assertEqual(context.field_access_logs, [HogQLFieldAccess(["person_id"], "person", "id", "person_id")])

        context = HogQLContext()
        self.assertEqual(self._translate("person.created_at", context), "person_created_at")
        self.assertEqual(
            context.field_access_logs,
            [HogQLFieldAccess(["person", "created_at"], "person", "created_at", "person_created_at")],
        )

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
        self.assertEqual(self._translate("countDistinct(event)"), "count(distinct event)")
        self.assertEqual(self._translate("countDistinctIf(event, 1 == 2)"), "countIf(distinct event, equals(1, 2))")
        self.assertEqual(self._translate("sumIf(1, 1 == 2)"), "sumIf(1, equals(1, 2))")

    def test_hogql_functions(self):
        context = HogQLContext()  # inline values
        self.assertEqual(self._translate("abs(1)"), "abs(1)")
        self.assertEqual(self._translate("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(self._translate("toInt('1')", context), "toInt64OrNull(%(hogql_val_0)s)")
        self.assertEqual(self._translate("toFloat('1.3')", context), "toFloat64OrNull(%(hogql_val_1)s)")

    def test_hogql_expr_parse_errors(self):
        self._assert_error("", "Empty query")
        self._assert_error("avg(bla)", "Unknown event field 'bla'")
        self._assert_error("count(2)", "Aggregation 'count' requires 0 arguments, found 1")
        self._assert_error("count(2,4)", "Aggregation 'count' requires 0 arguments, found 2")
        self._assert_error("countIf()", "Aggregation 'countIf' requires 1 argument, found 0")
        self._assert_error("countIf(2,4)", "Aggregation 'countIf' requires 1 argument, found 2")
        self._assert_error("hamburger(bla)", "Unsupported function call 'hamburger(...)'")
        self._assert_error("mad(bla)", "Unsupported function call 'mad(...)'")
        self._assert_error("yeet.the.cloud", "Unsupported property access: ['yeet', 'the', 'cloud']")
        self._assert_error("chipotle", "Unknown event field 'chipotle'")
        self._assert_error("person.chipotle", "Unknown person field 'chipotle'")
        self._assert_error(
            "avg(avg(properties.bla))", "Aggregation 'avg' cannot be nested inside another aggregation 'avg'."
        )

    def test_hogql_expr_syntax_errors(self):
        self._assert_error("(", "line 1, column 1: no viable alternative at input '('")
        self._assert_error("())", "line 1, column 1: no viable alternative at input '()'")
        self._assert_error("['properties']['value']", "Unsupported node: ColumnExprArray")
        self._assert_error("['properties']['value']['bla']", "Unsupported node: ColumnExprArray")
        self._assert_error("select query from events", "line 1, column 13: mismatched input 'from' expecting <EOF>")
        self._assert_error("this makes little sense", "2 validation errors for Column")
        self._assert_error("event makes little sense", "2 validation errors for Column")
        self._assert_error("1;2", "line 1, column 1: mismatched input ';' expecting")
        self._assert_error("b.a(bla)", "SyntaxError: line 1, column 3: mismatched input '(' expecting '.'")

    def test_hogql_returned_properties(self):
        context = HogQLContext()
        self._translate("avg(properties.prop) + avg(uuid) + event", context)
        self.assertEqual(
            context.field_access_logs,
            [
                HogQLFieldAccess(
                    ["properties", "prop"],
                    "event.properties",
                    "prop",
                    "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
                ),
                HogQLFieldAccess(["uuid"], "event", "uuid", "uuid"),
                HogQLFieldAccess(["event"], "event", "event", "event"),
            ],
        )
        self.assertEqual(context.found_aggregation, True)

        context = HogQLContext()
        self._translate("coalesce(event, properties.event)", context)
        self.assertEqual(
            context.field_access_logs,
            [
                HogQLFieldAccess(["event"], "event", "event", "event"),
                HogQLFieldAccess(
                    ["properties", "event"],
                    "event.properties",
                    "event",
                    "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
                ),
            ],
        )
        self.assertEqual(context.found_aggregation, False)

        context = HogQLContext()
        self._translate("count() + sum(timestamp)", context)
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["timestamp"], "event", "timestamp", "timestamp")]
        )
        self.assertEqual(context.found_aggregation, True)

        context = HogQLContext()
        self._translate("event + avg(event + properties.event) + avg(event + properties.event)", context)
        self.assertEqual(
            context.field_access_logs,
            [
                HogQLFieldAccess(["event"], "event", "event", "event"),
                HogQLFieldAccess(["event"], "event", "event", "event"),
                HogQLFieldAccess(
                    ["properties", "event"],
                    "event.properties",
                    "event",
                    "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
                ),
                HogQLFieldAccess(["event"], "event", "event", "event"),
                HogQLFieldAccess(
                    ["properties", "event"],
                    "event.properties",
                    "event",
                    "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_1)s), '^\"|\"$', '')",
                ),
            ],
        )
        self.assertEqual(context.found_aggregation, True)

    def test_hogql_logic(self):
        self.assertEqual(
            self._translate("event or timestamp"),
            "or(event, timestamp)",
        )
        self.assertEqual(
            self._translate("properties.bla and properties.bla2"),
            "and(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_1)s), '^\"|\"$', ''))",
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
        context = HogQLContext()
        self.assertEqual(self._translate("event == 'E'", context), "equals(event, %(hogql_val_0)s)")
        self.assertEqual(self._translate("event != 'E'", context), "notEquals(event, %(hogql_val_1)s)")
        self.assertEqual(self._translate("event > 'E'", context), "greater(event, %(hogql_val_2)s)")
        self.assertEqual(self._translate("event >= 'E'", context), "greaterOrEquals(event, %(hogql_val_3)s)")
        self.assertEqual(self._translate("event < 'E'", context), "less(event, %(hogql_val_4)s)")
        self.assertEqual(self._translate("event <= 'E'", context), "lessOrEquals(event, %(hogql_val_5)s)")
        self.assertEqual(self._translate("event like 'E'", context), "like(event, %(hogql_val_6)s)")
        self.assertEqual(self._translate("event not like 'E'", context), "not(like(event, %(hogql_val_7)s))")
        self.assertEqual(self._translate("event ilike 'E'", context), "ilike(event, %(hogql_val_8)s)")
        self.assertEqual(self._translate("event not ilike 'E'", context), "not(ilike(event, %(hogql_val_9)s))")
        self.assertEqual(self._translate("event in 'E'", context), "in(event, %(hogql_val_8)s)")
        self.assertEqual(self._translate("event not in 'E'", context), "not(in(event, %(hogql_val_9)s))")

    def test_hogql_comments(self):
        context = HogQLContext()
        self.assertEqual(self._translate("event -- something", context), "event")

    def test_hogql_special_root_properties(self):
        self.assertEqual(
            self._translate("*"),
            "tuple(uuid,event,properties,timestamp,team_id,distinct_id,elements_chain,created_at,person_id,person_created_at,person_properties)",
        )
        context = HogQLContext()
        self.assertEqual(
            self._translate("person", context),
            "tuple(distinct_id, person_id, person_created_at, replaceRegexpAll(JSONExtractRaw(person_properties, %(hogql_val_0)s), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(person_properties, %(hogql_val_1)s), '^\"|\"$', ''))",
        )
        self.assertEqual(context.values, {"hogql_val_0": "name", "hogql_val_1": "email"})
        self._assert_error("person + 1", 'Can not use the field "person" in an expression')

    def test_hogql_values(self):
        context = HogQLContext()
        self.assertEqual(self._translate("event == 'E'", context), "equals(event, %(hogql_val_0)s)")
        self.assertEqual(context.values, {"hogql_val_0": "E"})
        self.assertEqual(
            self._translate("coalesce(4.2, 5, 'lol', 'hoo')", context),
            "coalesce(4.2, 5, %(hogql_val_1)s, %(hogql_val_2)s)",
        )
        self.assertEqual(context.values, {"hogql_val_0": "E", "hogql_val_1": "lol", "hogql_val_2": "hoo"})

    def _assert_error(self, expr, expected_error):
        with self.assertRaises(ValueError) as context:
            self._translate(expr)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))
