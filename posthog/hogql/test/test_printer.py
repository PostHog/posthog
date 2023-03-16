from typing import Literal, Optional

from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.test.base import BaseTest


class TestPrinter(BaseTest):
    # Helper to always translate HogQL with a blank context
    def _expr(
        self, query: str, context: Optional[HogQLContext] = None, dialect: Literal["hogql", "clickhouse"] = "clickhouse"
    ) -> str:
        return translate_hogql(query, context or HogQLContext(team_id=self.team.pk), dialect)

    # Helper to always translate HogQL with a blank context,
    def _select(self, query: str, context: Optional[HogQLContext] = None) -> str:
        return print_ast(
            parse_select(query), context or HogQLContext(team_id=self.team.pk, enable_select_queries=True), "clickhouse"
        )

    def _assert_expr_error(self, expr, expected_error, dialect: Literal["hogql", "clickhouse"] = "clickhouse"):
        with self.assertRaises(ValueError) as context:
            self._expr(expr, None, dialect)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _assert_select_error(self, statement, expected_error):
        with self.assertRaises(ValueError) as context:
            self._select(statement, None)
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
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(
            self._expr("properties.$bla", context),
            "replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '')",
        )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=False):
            context = HogQLContext(team_id=self.team.pk, within_non_hogql_query=True, using_person_on_events=False)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(JSONExtractRaw(person_props, %(hogql_val_0)s), '^\"|\"$', '')",
            )
            context = HogQLContext(team_id=self.team.pk)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "events__pdi__person.properties___bla",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            context = HogQLContext(team_id=self.team.pk, within_non_hogql_query=True, using_person_on_events=True)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(JSONExtractRaw(person_properties, %(hogql_val_0)s), '^\"|\"$', '')",
            )
            context = HogQLContext(team_id=self.team.pk)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), '^\"|\"$', '')",
            )

    def test_hogql_properties(self):
        self.assertEqual(
            self._expr("event", HogQLContext(team_id=self.team.pk), "hogql"),
            "event",
        )
        self.assertEqual(
            self._expr("person", HogQLContext(team_id=self.team.pk), "hogql"),
            "person",
        )
        self.assertEqual(
            self._expr("person.properties.$browser", HogQLContext(team_id=self.team.pk), "hogql"),
            "person.properties.$browser",
        )
        self.assertEqual(
            self._expr("properties.$browser", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.$browser",
        )
        self.assertEqual(
            self._expr("properties.`$browser with a space`", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr('properties."$browser with a space"', HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr("properties['$browser with a space']", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr("properties['$browser with a ` tick']", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.`$browser with a \\` tick`",
        )
        self.assertEqual(
            self._expr("properties['$browser \\\\with a \\n` tick']", HogQLContext(team_id=self.team.pk), "hogql"),
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
        self.assertEqual(self._expr("properties['$browser']"), "events.`mat_$browser`")

        materialize("events", "withoutdollar")
        self.assertEqual(self._expr("properties['withoutdollar']"), "events.mat_withoutdollar")

        materialize("events", "$browser and string")
        self.assertEqual(self._expr("properties['$browser and string']"), "events.`mat_$browser_and_string`")

        materialize("events", "$browser%%%#@!@")
        self.assertEqual(self._expr("properties['$browser%%%#@!@']"), "events.`mat_$browser_______`")

    def test_methods(self):
        self.assertEqual(self._expr("count()"), "count()")
        self.assertEqual(self._expr("count(distinct event)"), "count(DISTINCT event)")
        self.assertEqual(self._expr("countIf(distinct event, 1 == 2)"), "countIf(DISTINCT event, equals(1, 2))")
        self.assertEqual(self._expr("sumIf(1, 1 == 2)"), "sumIf(1, equals(1, 2))")

    def test_functions(self):
        context = HogQLContext(team_id=self.team.pk)  # inline values
        self.assertEqual(self._expr("abs(1)"), "abs(1)")
        self.assertEqual(self._expr("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(self._expr("toInt('1')", context), "toInt64OrNull(%(hogql_val_0)s)")
        self.assertEqual(self._expr("toFloat('1.3')", context), "toFloat64OrNull(%(hogql_val_1)s)")

    def test_expr_parse_errors(self):
        self._assert_expr_error("", "Empty query")
        self._assert_expr_error("avg(bla)", "Unable to resolve field: bla")
        self._assert_expr_error("count(1,2,3,4)", "Aggregation 'count' requires between 0 and 1 arguments, found 4")
        self._assert_expr_error("countIf()", "Aggregation 'countIf' requires between 1 and 2 arguments, found 0")
        self._assert_expr_error("countIf(2,3,4)", "Aggregation 'countIf' requires between 1 and 2 arguments, found 3")
        self._assert_expr_error("hamburger(event)", "Unsupported function call 'hamburger(...)'")
        self._assert_expr_error("mad(event)", "Unsupported function call 'mad(...)'")
        self._assert_expr_error("yeet.the.cloud", "Unable to resolve field: yeet")
        self._assert_expr_error("chipotle", "Unable to resolve field: chipotle")
        self._assert_expr_error(
            "avg(avg(properties.bla))", "Aggregation 'avg' cannot be nested inside another aggregation 'avg'."
        )
        self._assert_expr_error("person.chipotle", "Field not found: chipotle")
        self._assert_expr_error("properties.no.json.yet", "JSON property traversal is not yet supported")

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
            "or(event, timestamp, true, count())",
        )
        self.assertEqual(
            self._expr("event or not timestamp"),
            "or(event, not(timestamp))",
        )

    def test_comparisons(self):
        context = HogQLContext(team_id=self.team.pk)
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
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(self._expr("event -- something", context), "event")

    def test_values(self):
        context = HogQLContext(team_id=self.team.pk)
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
            f"SELECT 1 AS `-- select team_id` FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )
        # Some aliases are funny, but that's what the antlr syntax permits, and ClickHouse doesn't complain either
        self.assertEqual(self._expr("event makes little sense"), "((event AS makes) AS little) AS sense")

    def test_select(self):
        self.assertEqual(self._select("select 1"), "SELECT 1 LIMIT 65535")
        self.assertEqual(self._select("select 1 + 2"), "SELECT plus(1, 2) LIMIT 65535")
        self.assertEqual(self._select("select 1 + 2, 3"), "SELECT plus(1, 2), 3 LIMIT 65535")
        self.assertEqual(
            self._select("select 1 + 2, 3 + 4 from events"),
            f"SELECT plus(1, 2), plus(3, 4) FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

    def test_select_alias(self):
        # currently not supported!
        self.assertEqual(self._select("select 1 as b"), "SELECT 1 AS b LIMIT 65535")
        self.assertEqual(
            self._select("select 1 from events as e"),
            f"SELECT 1 FROM events AS e WHERE equals(e.team_id, {self.team.pk}) LIMIT 65535",
        )

    def test_select_from(self):
        self.assertEqual(
            self._select("select 1 from events"),
            f"SELECT 1 FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )
        self._assert_select_error("select 1 from other", 'Unknown table "other".')

    def test_select_where(self):
        self.assertEqual(
            self._select("select 1 from events where 1 == 2"),
            f"SELECT 1 FROM events WHERE and(equals(team_id, {self.team.pk}), equals(1, 2)) LIMIT 65535",
        )

    def test_select_having(self):
        self.assertEqual(
            self._select("select 1 from events having 1 == 2"),
            f"SELECT 1 FROM events WHERE equals(team_id, {self.team.pk}) HAVING equals(1, 2) LIMIT 65535",
        )

    def test_select_prewhere(self):
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2"),
            f"SELECT 1 FROM events PREWHERE equals(1, 2) WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2 where 2 == 3"),
            f"SELECT 1 FROM events PREWHERE equals(1, 2) WHERE and(equals(team_id, {self.team.pk}), equals(2, 3)) LIMIT 65535",
        )

    def test_select_order_by(self):
        self.assertEqual(
            self._select("select event from events order by event"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) ORDER BY event ASC LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events order by event desc"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) ORDER BY event DESC LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events order by event desc, timestamp"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) ORDER BY event DESC, timestamp ASC LIMIT 65535",
        )

    def test_select_limit(self):
        self.assertEqual(
            self._select("select event from events limit 10"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10000000"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )
        self.assertEqual(
            self._select("select event from events limit (select 1000000000)"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT min2(65535, (SELECT 1000000000))",
        )

        self.assertEqual(
            self._select("select event from events limit (select 1000000000) with ties"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT min2(65535, (SELECT 1000000000)) WITH TIES",
        )

    def test_select_offset(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 10"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 10 OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 10 OFFSET 0",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 with ties"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 10 OFFSET 0 WITH TIES",
        )

    def test_select_limit_by(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 by 1,event"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 10 OFFSET 0 BY 1, event",
        )

    def test_select_group_by(self):
        self.assertEqual(
            self._select("select event from events group by event, timestamp"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) GROUP BY event, timestamp LIMIT 65535",
        )

    def test_select_distinct(self):
        self.assertEqual(
            self._select("select distinct event from events group by event, timestamp"),
            f"SELECT DISTINCT event FROM events WHERE equals(team_id, {self.team.pk}) GROUP BY event, timestamp LIMIT 65535",
        )

    def test_select_subquery(self):
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp)"),
            f"SELECT event FROM (SELECT DISTINCT event FROM events WHERE equals(team_id, {self.team.pk}) GROUP BY event, timestamp) LIMIT 65535",
        )
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp) e"),
            f"SELECT e.event FROM (SELECT DISTINCT event FROM events WHERE equals(team_id, {self.team.pk}) GROUP BY event, timestamp) AS e LIMIT 65535",
        )

    def test_select_union_all(self):
        self.assertEqual(
            self._select("SELECT event FROM events UNION ALL SELECT event FROM events WHERE 1 = 2"),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535 UNION ALL SELECT event FROM events WHERE and(equals(team_id, {self.team.pk}), equals(1, 2)) LIMIT 65535",
        )
        self.assertEqual(
            self._select(
                "SELECT event FROM events UNION ALL SELECT event FROM events WHERE 1 = 2 UNION ALL SELECT event FROM events WHERE 1 = 2"
            ),
            f"SELECT event FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535 UNION ALL SELECT event FROM events WHERE and(equals(team_id, {self.team.pk}), equals(1, 2)) LIMIT 65535 UNION ALL SELECT event FROM events WHERE and(equals(team_id, {self.team.pk}), equals(1, 2)) LIMIT 65535",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL (SELECT 1 UNION ALL SELECT 1) UNION ALL SELECT 1"),
            "SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1"),
            "SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535 UNION ALL SELECT 1 LIMIT 65535",
        )
        self.assertEqual(
            self._select("SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1)"),
            "SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1) LIMIT 65535",
        )

    def test_select_sample(self):
        self.assertEqual(
            self._select("SELECT event FROM events SAMPLE 1"),
            f"SELECT event FROM events SAMPLE 1 WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

        self.assertEqual(
            self._select("SELECT event FROM events SAMPLE 0.1 OFFSET 1/10"),
            f"SELECT event FROM events SAMPLE 0.1 OFFSET 1/10 WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

        self.assertEqual(
            self._select("SELECT event FROM events SAMPLE 2/78 OFFSET 999"),
            f"SELECT event FROM events SAMPLE 2/78 OFFSET 999 WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=False):
            self.assertEqual(
                self._select(
                    "SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id"
                ),
                f"SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN person ON equals(id, events__pdi.person_id) INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(person.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 65535",
            )

            self.assertEqual(
                self._select(
                    "SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id"
                ),
                f"SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN person SAMPLE 0.1 ON equals(id, events__pdi.person_id) INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(person.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 65535",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            self.assertEqual(
                self._select(
                    "SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id"
                ),
                f"SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN person ON equals(id, person_id) WHERE and(equals(person.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 65535",
            )

            self.assertEqual(
                self._select(
                    "SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id"
                ),
                f"SELECT event FROM events SAMPLE 2/78 OFFSET 999 JOIN person SAMPLE 0.1 ON equals(id, person_id) WHERE and(equals(person.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 65535",
            )

    def test_count_distinct(self):
        self.assertEqual(
            self._select("SELECT count(distinct event) FROM events"),
            f"SELECT count(DISTINCT event) FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

    def test_count_star(self):
        self.assertEqual(
            self._select("SELECT count(*) FROM events"),
            f"SELECT count(*) FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )

    def test_count_if_distinct(self):
        self.assertEqual(
            self._select("SELECT countIf(distinct event, event like '%a%') FROM events"),
            f"SELECT countIf(DISTINCT event, like(event, %(hogql_val_0)s)) FROM events WHERE equals(team_id, {self.team.pk}) LIMIT 65535",
        )
