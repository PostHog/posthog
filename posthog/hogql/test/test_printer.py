from typing import Literal, Optional

from django.test.testcases import TestCase

from posthog.hogql.context import HogQLContext, HogQLFieldAccess
from posthog.hogql.hogql import translate_hogql


class TestPrinter(TestCase):
    # Helper to always translate HogQL with a blank context
    def _expr(
        self, query: str, context: Optional[HogQLContext] = None, dialect: Literal["hogql", "clickhouse"] = "clickhouse"
    ) -> str:
        return translate_hogql(query, context or HogQLContext(), dialect)

    # Helper to always translate HogQL with a blank context,
    def _select(
        self, query: str, context: Optional[HogQLContext] = None, dialect: Literal["hogql", "clickhouse"] = "clickhouse"
    ) -> str:
        return translate_hogql(query, context or HogQLContext(select_team_id=42), dialect)

    def _assert_expr_error(self, expr, expected_error, dialect: Literal["hogql", "clickhouse"] = "clickhouse"):
        with self.assertRaises(ValueError) as context:
            self._expr(expr, None, dialect)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _assert_select_error(self, statement, expected_error, dialect: Literal["hogql", "clickhouse"] = "clickhouse"):
        with self.assertRaises(ValueError) as context:
            self._select(statement, None, dialect)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def test_literals(self):
        self.assertEqual(self._expr("1 + 2"), "plus(1, 2)")
        self.assertEqual(self._expr("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(self._expr("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(self._expr("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(self._expr("1.0 % 2.66"), "modulo(1.0, 2.66)")
        self.assertEqual(self._expr("'string'"), "%(hogql_val_0)s")

    def test_equals_null(self):
        self.assertEqual(self._expr("1 == null"), "isNull(1)")
        self.assertEqual(self._expr("1 != null"), "isNotNull(1)")

    def test_fields_and_properties(self):
        self.assertEqual(
            self._expr("properties.bla"),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._expr("properties['bla']"),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )
        context = HogQLContext()
        self.assertEqual(
            self._expr("properties.$bla", context),
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
            self._expr("person.properties.bla", context),
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
        self.assertEqual(self._expr("uuid", context), "uuid")
        self.assertEqual(context.field_access_logs, [HogQLFieldAccess(["uuid"], "event", "uuid", "uuid")])

        context = HogQLContext()
        self.assertEqual(self._expr("event", context), "event")
        self.assertEqual(context.field_access_logs, [HogQLFieldAccess(["event"], "event", "event", "event")])

        context = HogQLContext()
        self.assertEqual(self._expr("timestamp", context), "timestamp")
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["timestamp"], "event", "timestamp", "timestamp")]
        )

        context = HogQLContext()
        self.assertEqual(self._expr("distinct_id", context), "distinct_id")
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["distinct_id"], "event", "distinct_id", "distinct_id")]
        )

        context = HogQLContext()
        self.assertEqual(self._expr("person.id", context), "events.person_id")
        self.assertEqual(
            context.field_access_logs,
            [HogQLFieldAccess(["person", "id"], "person", "id", "events.person_id")],
        )

        context = HogQLContext()
        self.assertEqual(self._expr("person.created_at", context), "events.person_created_at")
        self.assertEqual(
            context.field_access_logs,
            [HogQLFieldAccess(["person", "created_at"], "person", "created_at", "events.person_created_at")],
        )

    def test_hogql_properties(self):
        self.assertEqual(
            self._expr("event", HogQLContext(), "hogql"),
            "event",
        )
        self.assertEqual(
            self._expr("person", HogQLContext(), "hogql"),
            "person",
        )
        self.assertEqual(
            self._expr("person.properties.$browser", HogQLContext(), "hogql"),
            "person.properties.$browser",
        )
        self.assertEqual(
            self._expr("properties.$browser", HogQLContext(), "hogql"),
            "properties.$browser",
        )
        self.assertEqual(
            self._expr("properties.`$browser with a space`", HogQLContext(), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr('properties."$browser with a space"', HogQLContext(), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr("properties['$browser with a space']", HogQLContext(), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr("properties['$browser with a ` tick']", HogQLContext(), "hogql"),
            "properties.`$browser with a \\` tick`",
        )
        self.assertEqual(
            self._expr("properties['$browser \\\\with a \\n` tick']", HogQLContext(), "hogql"),
            "properties.`$browser \\\\with a \\n\\` tick`",
        )
        self._assert_expr_error("properties.0", "Unsupported node: ColumnExprTupleAccess", "hogql")
        self._assert_expr_error(
            "properties.'no strings'", "mismatched input ''no strings'' expecting DECIMAL_LITERAL", "hogql"
        )

    def test_materialized_fields_and_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")
        self.assertEqual(self._expr("properties['$browser']"), "`mat_$browser`")

        materialize("events", "withoutdollar")
        self.assertEqual(self._expr("properties['withoutdollar']"), "mat_withoutdollar")

        materialize("events", "$browser and string")
        self.assertEqual(self._expr("properties['$browser and string']"), "`mat_$browser_and_string`")

        materialize("events", "$browser%%%#@!@")
        self.assertEqual(self._expr("properties['$browser%%%#@!@']"), "`mat_$browser_______`")

        materialize("events", "$initial_waffle", table_column="person_properties")
        self.assertEqual(self._expr("person.properties['$initial_waffle']"), "`mat_pp_$initial_waffle`")

    def test_methods(self):
        self.assertEqual(self._expr("count()"), "count(*)")
        self.assertEqual(self._expr("countDistinct(event)"), "count(distinct event)")
        self.assertEqual(self._expr("countDistinctIf(event, 1 == 2)"), "countIf(distinct event, equals(1, 2))")
        self.assertEqual(self._expr("sumIf(1, 1 == 2)"), "sumIf(1, equals(1, 2))")

    def test_functions(self):
        context = HogQLContext()  # inline values
        self.assertEqual(self._expr("abs(1)"), "abs(1)")
        self.assertEqual(self._expr("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(self._expr("toInt('1')", context), "toInt64OrNull(%(hogql_val_0)s)")
        self.assertEqual(self._expr("toFloat('1.3')", context), "toFloat64OrNull(%(hogql_val_1)s)")

    def test_expr_parse_errors(self):
        self._assert_expr_error("", "Empty query")
        self._assert_expr_error("avg(bla)", "Unable to resolve field: bla")
        self._assert_expr_error("count(2)", "Aggregation 'count' requires 0 arguments, found 1")
        self._assert_expr_error("count(2,4)", "Aggregation 'count' requires 0 arguments, found 2")
        self._assert_expr_error("countIf()", "Aggregation 'countIf' requires 1 argument, found 0")
        self._assert_expr_error("countIf(2,4)", "Aggregation 'countIf' requires 1 argument, found 2")
        self._assert_expr_error("hamburger(event)", "Unsupported function call 'hamburger(...)'")
        self._assert_expr_error("mad(event)", "Unsupported function call 'mad(...)'")
        self._assert_expr_error("yeet.the.cloud", "Unable to resolve field: yeet")
        self._assert_expr_error("chipotle", "Unable to resolve field: chipotle")
        self._assert_expr_error(
            "avg(avg(properties.bla))", "Aggregation 'avg' cannot be nested inside another aggregation 'avg'."
        )
        self._assert_expr_error("person.chipotle", 'Field "chipotle" not found on table EventsPersonSubTable')

    def test_expr_syntax_errors(self):
        self._assert_expr_error("(", "line 1, column 1: no viable alternative at input '('")
        self._assert_expr_error("())", "line 1, column 1: no viable alternative at input '()'")
        self._assert_expr_error("['properties']['value']", "Unsupported node: ColumnExprArray")
        self._assert_expr_error("['properties']['value']['bla']", "Unsupported node: ColumnExprArray")
        self._assert_expr_error(
            "select query from events", "line 1, column 13: mismatched input 'from' expecting <EOF>"
        )
        self._assert_expr_error("this makes little sense", "Unable to resolve field: this")
        self._assert_expr_error("1;2", "line 1, column 1: mismatched input ';' expecting")
        self._assert_expr_error("b.a(bla)", "SyntaxError: line 1, column 3: mismatched input '(' expecting '.'")

    def test_returned_properties(self):
        context = HogQLContext()
        self._expr("avg(properties.prop) + avg(uuid) + event", context)
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
        self._expr("coalesce(event, properties.event)", context)
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
        self._expr("count() + sum(timestamp)", context)
        self.assertEqual(
            context.field_access_logs, [HogQLFieldAccess(["timestamp"], "event", "timestamp", "timestamp")]
        )
        self.assertEqual(context.found_aggregation, True)

        context = HogQLContext()
        self._expr("event + avg(event + properties.event) + avg(event + properties.event)", context)
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

    def test_logic(self):
        self.assertEqual(
            self._expr("event or timestamp"),
            "or(event, timestamp)",
        )
        self.assertEqual(
            self._expr("properties.bla and properties.bla2"),
            "and(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_1)s), '^\"|\"$', ''))",
        )
        self.assertEqual(
            self._expr("event or timestamp or true or count()"),
            "or(event, timestamp, true, count(*))",
        )
        self.assertEqual(
            self._expr("event or not timestamp"),
            "or(event, not(timestamp))",
        )

    def test_comparisons(self):
        context = HogQLContext()
        self.assertEqual(self._expr("event == 'E'", context), "equals(event, %(hogql_val_0)s)")
        self.assertEqual(self._expr("event != 'E'", context), "notEquals(event, %(hogql_val_1)s)")
        self.assertEqual(self._expr("event > 'E'", context), "greater(event, %(hogql_val_2)s)")
        self.assertEqual(self._expr("event >= 'E'", context), "greaterOrEquals(event, %(hogql_val_3)s)")
        self.assertEqual(self._expr("event < 'E'", context), "less(event, %(hogql_val_4)s)")
        self.assertEqual(self._expr("event <= 'E'", context), "lessOrEquals(event, %(hogql_val_5)s)")
        self.assertEqual(self._expr("event like 'E'", context), "like(event, %(hogql_val_6)s)")
        self.assertEqual(self._expr("event not like 'E'", context), "not(like(event, %(hogql_val_7)s))")
        self.assertEqual(self._expr("event ilike 'E'", context), "ilike(event, %(hogql_val_8)s)")
        self.assertEqual(self._expr("event not ilike 'E'", context), "not(ilike(event, %(hogql_val_9)s))")
        self.assertEqual(self._expr("event in 'E'", context), "in(event, %(hogql_val_10)s)")
        self.assertEqual(self._expr("event not in 'E'", context), "not(in(event, %(hogql_val_11)s))")

    def test_comments(self):
        context = HogQLContext()
        self.assertEqual(self._expr("event -- something", context), "event")

    def test_values(self):
        context = HogQLContext()
        self.assertEqual(self._expr("event == 'E'", context), "equals(event, %(hogql_val_0)s)")
        self.assertEqual(context.values, {"hogql_val_0": "E"})
        self.assertEqual(
            self._expr("coalesce(4.2, 5, 'lol', 'hoo')", context),
            "coalesce(4.2, 5, %(hogql_val_1)s, %(hogql_val_2)s)",
        )
        self.assertEqual(context.values, {"hogql_val_0": "E", "hogql_val_1": "lol", "hogql_val_2": "hoo"})

    def test_alias_keywords(self):
        self._assert_expr_error("1 as team_id", "Alias 'team_id' is a reserved keyword.")
        self._assert_expr_error("1 as true", "Alias 'true' is a reserved keyword.")
        self._assert_select_error("select 1 as team_id from events", "Alias 'team_id' is a reserved keyword.")
        self.assertEqual(
            self._select("select 1 as `-- select team_id` from events"),
            "SELECT 1 AS `-- select team_id` FROM events WHERE equals(team_id, 42) LIMIT 65535",
        )
        # Some aliases are funny, but that's what the antlr syntax permits, and ClickHouse doesn't complain either
        self.assertEqual(self._expr("event makes little sense"), "((event AS makes) AS little) AS sense")

    def test_select(self):
        self.assertEqual(self._select("select 1"), "SELECT 1 LIMIT 65535")
        self.assertEqual(self._select("select 1 + 2"), "SELECT plus(1, 2) LIMIT 65535")
        self.assertEqual(self._select("select 1 + 2, 3"), "SELECT plus(1, 2), 3 LIMIT 65535")
        self.assertEqual(
            self._select("select 1 + 2, 3 + 4 from events"),
            "SELECT plus(1, 2), plus(3, 4) FROM events WHERE equals(team_id, 42) LIMIT 65535",
        )

    def test_select_alias(self):
        # currently not supported!
        self.assertEqual(self._select("select 1 as b"), "SELECT 1 AS b LIMIT 65535")
        self.assertEqual(
            self._select("select 1 from events as e"),
            "SELECT 1 FROM events AS e WHERE equals(e.team_id, 42) LIMIT 65535",
        )

    def test_select_from(self):
        self.assertEqual(
            self._select("select 1 from events"), "SELECT 1 FROM events WHERE equals(team_id, 42) LIMIT 65535"
        )
        self._assert_select_error("select 1 from other", 'Unknown table "other".')

    def test_select_where(self):
        self.assertEqual(
            self._select("select 1 from events where 1 == 2"),
            "SELECT 1 FROM events WHERE and(equals(team_id, 42), equals(1, 2)) LIMIT 65535",
        )

    def test_select_having(self):
        self.assertEqual(
            self._select("select 1 from events having 1 == 2"),
            "SELECT 1 FROM events WHERE equals(team_id, 42) HAVING equals(1, 2) LIMIT 65535",
        )

    def test_select_prewhere(self):
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2"),
            "SELECT 1 FROM events WHERE equals(team_id, 42) PREWHERE equals(1, 2) LIMIT 65535",
        )

    def test_select_order_by(self):
        self.assertEqual(
            self._select("select event from events order by event"),
            "SELECT event FROM events WHERE equals(team_id, 42) ORDER BY event ASC LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events order by event desc"),
            "SELECT event FROM events WHERE equals(team_id, 42) ORDER BY event DESC LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events order by event desc, timestamp"),
            "SELECT event FROM events WHERE equals(team_id, 42) ORDER BY event DESC, timestamp ASC LIMIT 65535",
        )

    def test_select_limit(self):
        self.assertEqual(
            self._select("select event from events limit 10"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10000000"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events limit (select 1000000000)"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT min2(65535, (SELECT 1000000000))",
        )

        self.assertEqual(
            self._select("select event from events limit (select 1000000000) with ties"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT min2(65535, (SELECT 1000000000)) WITH TIES",
        )

    def test_select_offset(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 10"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 10 OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 10 OFFSET 0",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 with ties"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 10 OFFSET 0 WITH TIES",
        )

    def test_select_limit_by(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 by 1,event"),
            "SELECT event FROM events WHERE equals(team_id, 42) LIMIT 10 OFFSET 0 BY 1, event",
        )

    def test_select_group_by(self):
        self.assertEqual(
            self._select("select event from events group by event, timestamp"),
            "SELECT event FROM events WHERE equals(team_id, 42) GROUP BY event, timestamp LIMIT 65535",
        )

    def test_select_distinct(self):
        self.assertEqual(
            self._select("select distinct event from events group by event, timestamp"),
            "SELECT DISTINCT event FROM events WHERE equals(team_id, 42) GROUP BY event, timestamp LIMIT 65535",
        )

    def test_select_subquery(self):
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp)"),
            "SELECT event FROM (SELECT DISTINCT event FROM events WHERE equals(team_id, 42) GROUP BY event, timestamp) LIMIT 65535",
        )
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp) e"),
            "SELECT e.event FROM (SELECT DISTINCT event FROM events WHERE equals(team_id, 42) GROUP BY event, timestamp) AS e LIMIT 65535",
        )
