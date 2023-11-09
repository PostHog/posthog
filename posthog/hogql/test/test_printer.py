from typing import Literal, Optional, Dict

import pytest
from django.test import override_settings

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DateDatabaseField
from posthog.hogql.errors import HogQLException
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast, to_printed_hogql
from posthog.models.team.team import WeekStartDay
from posthog.schema import HogQLQueryModifiers, PersonsArgMaxVersion
from posthog.test.base import BaseTest
from posthog.utils import PersonOnEventsMode


class TestPrinter(BaseTest):
    maxDiff = None

    # Helper to always translate HogQL with a blank context
    def _expr(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ) -> str:
        return translate_hogql(query, context or HogQLContext(team_id=self.team.pk), dialect)

    # Helper to always translate HogQL with a blank context,
    def _select(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        placeholders: Optional[Dict[str, ast.Expr]] = None,
    ) -> str:
        return print_ast(
            parse_select(query, placeholders=placeholders),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )

    def _assert_expr_error(
        self,
        expr,
        expected_error,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ):
        with self.assertRaises(HogQLException) as context:
            self._expr(expr, None, dialect)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _assert_select_error(self, statement, expected_error):
        with self.assertRaises(HogQLException) as context:
            self._select(statement, None)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _pretty(self, query: str):
        printed = print_ast(
            parse_select(query),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "hogql",
            pretty=True,
        )
        return printed

    def test_to_printed_hogql(self):
        expr = parse_select("select 1 + 2, 3 from events")
        repsponse = to_printed_hogql(expr, self.team.pk)
        self.assertEqual(repsponse, "SELECT\n    plus(1, 2),\n    3\nFROM\n    events\nLIMIT 10000")

    def test_literals(self):
        self.assertEqual(self._expr("1 + 2"), "plus(1, 2)")
        self.assertEqual(self._expr("-1 + 2"), "plus(-1, 2)")
        self.assertEqual(self._expr("-1 - 2 / (3 + 4)"), "minus(-1, divide(2, plus(3, 4)))")
        self.assertEqual(self._expr("1.0 * 2.66"), "multiply(1.0, 2.66)")
        self.assertEqual(self._expr("1.0 % 2.66"), "modulo(1.0, 2.66)")
        self.assertEqual(self._expr("'string'"), "%(hogql_val_0)s")

    def test_arrays(self):
        self.assertEqual(self._expr("[]"), "[]")
        self.assertEqual(self._expr("[1,2]"), "[1, 2]")

    def test_array_access(self):
        self.assertEqual(self._expr("[1,2,3][1]"), "[1, 2, 3][1]")
        self.assertEqual(
            self._expr("events.properties[1]"),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(self._expr("events.event[1 + 2]"), "events.event[plus(1, 2)]")

    def test_tuples(self):
        self.assertEqual(self._expr("(1,2)"), "tuple(1, 2)")
        self.assertEqual(self._expr("(1,2,[])"), "tuple(1, 2, [])")

    def test_lambdas(self):
        self.assertEqual(
            self._expr("arrayMap(x -> x*2, [1,2,3])"),
            "arrayMap(x -> multiply(x, 2), [1, 2, 3])",
        )
        self.assertEqual(
            self._expr("arrayMap((x, y) -> x*y, [1,2,3])"),
            "arrayMap((x, y) -> multiply(x, y), [1, 2, 3])",
        )

    def test_equals_null(self):
        self.assertEqual(self._expr("event == null"), "isNull(events.event)")
        self.assertEqual(self._expr("event != null"), "isNotNull(events.event)")
        self.assertEqual(self._expr("1 == null"), "0")
        self.assertEqual(self._expr("1 != null"), "1")

    def test_fields_and_properties(self):
        self.assertEqual(
            self._expr("properties.bla"),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._expr("properties['bla']"),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(
            self._expr("properties['bla']['bla']"),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
        )
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(
            self._expr("properties.$bla", context),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
        )

        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            context = HogQLContext(
                team_id=self.team.pk,
                within_non_hogql_query=True,
                modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.DISABLED),
            )
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person_props, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
            )
            context = HogQLContext(team_id=self.team.pk)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "events__pdi__person.properties___bla",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            context = HogQLContext(
                team_id=self.team.pk,
                within_non_hogql_query=True,
                modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.V1_ENABLED),
            )
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person_properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
            )
            context = HogQLContext(team_id=self.team.pk)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
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
            self._expr(
                "person.properties.$browser",
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "person.properties.$browser",
        )
        self.assertEqual(
            self._expr("properties.$browser", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.$browser",
        )
        self.assertEqual(
            self._expr(
                "properties.`$browser with a space`",
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr(
                'properties."$browser with a space"',
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr(
                "properties['$browser with a space']",
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "properties.`$browser with a space`",
        )
        self.assertEqual(
            self._expr(
                "properties['$browser with a ` tick']",
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "properties.`$browser with a \\` tick`",
        )
        self.assertEqual(
            self._expr(
                "properties['$browser \\\\with a \\n` tick']",
                HogQLContext(team_id=self.team.pk),
                "hogql",
            ),
            "properties.`$browser \\\\with a \\n\\` tick`",
        )
        # "dot NUMBER" means "tuple access" in clickhouse. To access strings properties, wrap them in `backquotes`
        self.assertEqual(
            self._expr("properties.1", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.1",
        )
        self.assertEqual(
            self._expr("properties.`1`", HogQLContext(team_id=self.team.pk), "hogql"),
            "properties.`1`",
        )
        self._assert_expr_error(
            "properties.'no strings'",
            "no viable alternative at input '.'no strings'",
            "hogql",
        )

    def test_hogql_properties_json(self):
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(
            self._expr("properties.nomat.json.yet", context),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(
            context.values,
            {"hogql_val_0": "nomat", "hogql_val_1": "json", "hogql_val_2": "yet"},
        )

    def test_hogql_properties_materialized_json_access(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return

        materialize("events", "withmat")
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(
            self._expr("properties.withmat.json.yet", context),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(nullIf(nullIf(events.mat_withmat, ''), 'null'), %(hogql_val_0)s, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(context.values, {"hogql_val_0": "json", "hogql_val_1": "yet"})

    def test_materialized_fields_and_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")
        self.assertEqual(
            self._expr("properties['$browser']"),
            "nullIf(nullIf(events.`mat_$browser`, ''), 'null')",
        )

        materialize("events", "withoutdollar")
        self.assertEqual(
            self._expr("properties['withoutdollar']"),
            "nullIf(nullIf(events.mat_withoutdollar, ''), 'null')",
        )

        materialize("events", "$browser and string")
        self.assertEqual(
            self._expr("properties['$browser and string']"),
            "nullIf(nullIf(events.`mat_$browser_and_string`, ''), 'null')",
        )

        materialize("events", "$browser%%%#@!@")
        self.assertEqual(
            self._expr("properties['$browser%%%#@!@']"),
            "nullIf(nullIf(events.`mat_$browser_______`, ''), 'null')",
        )

    def test_methods(self):
        self.assertEqual(self._expr("count()"), "count()")
        self.assertEqual(self._expr("count(distinct event)"), "count(DISTINCT events.event)")
        self.assertEqual(
            self._expr("countIf(distinct event, 1 == 2)"),
            "countIf(DISTINCT events.event, 0)",
        )
        self.assertEqual(self._expr("sumIf(1, 1 == 2)"), "sumIf(1, 0)")

    def test_functions(self):
        context = HogQLContext(team_id=self.team.pk)  # inline values
        self.assertEqual(self._expr("abs(1)"), "abs(1)")
        self.assertEqual(self._expr("max2(1,2)"), "max2(1, 2)")
        self.assertEqual(self._expr("toInt('1')", context), "toInt64OrNull(%(hogql_val_0)s)")
        self.assertEqual(self._expr("toFloat('1.3')", context), "toFloat64OrNull(%(hogql_val_1)s)")
        self.assertEqual(self._expr("quantile(0.95)( event )"), "quantile(0.95)(events.event)")

    def test_expr_parse_errors(self):
        self._assert_expr_error("", "Empty query")
        self._assert_expr_error("avg(bla)", "Unable to resolve field: bla")
        self._assert_expr_error("count(1,2,3,4)", "Aggregation 'count' expects at most 1 argument, found 4")
        self._assert_expr_error("countIf()", "Aggregation 'countIf' expects at least 1 argument, found 0")
        self._assert_expr_error(
            "countIf(2,3,4)",
            "Aggregation 'countIf' expects at most 2 arguments, found 3",
        )
        self._assert_expr_error("uniq()", "Aggregation 'uniq' expects at least 1 argument, found 0")
        self._assert_expr_error(
            "quantile(event)",
            "Aggregation 'quantile' requires parameters in addition to arguments",
        )
        self._assert_expr_error(
            "quantile()(event)",
            "Aggregation 'quantile' requires parameters in addition to arguments",
        )
        self._assert_expr_error(
            "quantile(0.5, 2)(event)",
            "Aggregation 'quantile' expects 1 parameter, found 2",
        )
        self._assert_expr_error("sparkline()", "Function 'sparkline' expects 1 argument, found 0")
        self._assert_expr_error("hamburger(event)", "Unsupported function call 'hamburger(...)'")
        self._assert_expr_error("mad(event)", "Unsupported function call 'mad(...)'")
        self._assert_expr_error(
            "noway(event)",
            "Unsupported function call 'noway(...)'. Perhaps you meant 'now(...)'?",
        )
        self._assert_expr_error(
            "tostring(event)",
            "Unsupported function call 'tostring(...)'. Perhaps you meant 'toString(...)'?",
        )
        self._assert_expr_error("yeet.the.cloud", "Unable to resolve field: yeet")
        self._assert_expr_error("chipotle", "Unable to resolve field: chipotle")
        self._assert_expr_error(
            "avg(avg(properties.bla))",
            "Aggregation 'avg' cannot be nested inside another aggregation 'avg'.",
        )
        self._assert_expr_error("person.chipotle", "Field not found: chipotle")
        self._assert_expr_error("properties.0", "SQL indexes start from one, not from zero. E.g: array[1]")
        self._assert_expr_error(
            "properties.id.0",
            "SQL indexes start from one, not from zero. E.g: array[1]",
        )
        self._assert_expr_error(
            "event as `as%d`",
            'The HogQL identifier "as%d" is not permitted as it contains the "%" character',
        )

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_expr_parse_errors_poe_on(self):
        # VirtualTable
        self._assert_expr_error("person", "Can't select a table when a column is expected: person")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_expr_parse_errors_poe_off(self):
        # LazyTable
        self._assert_expr_error("person", "Can't select a table when a column is expected: person")

    def test_expr_syntax_errors(self):
        self._assert_expr_error("(", "no viable alternative at input '('")
        self._assert_expr_error("())", "no viable alternative at input '()'")
        self._assert_expr_error("(3 57", "no viable alternative at input '(3 57'")
        self._assert_expr_error("select query from events", "mismatched input 'from' expecting <EOF>")
        self._assert_expr_error("this makes little sense", "Unable to resolve field: this")
        self._assert_expr_error("1;2", "mismatched input ';' expecting <EOF>")
        self._assert_expr_error("b.a(bla)", "mismatched input '(' expecting '.'")

    def test_logic(self):
        self.assertEqual(
            self._expr("event or timestamp"),
            "or(events.event, toTimeZone(events.timestamp, %(hogql_val_0)s))",
        )
        self.assertEqual(
            self._expr("properties.bla and properties.bla2"),
            "and(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))",
        )
        self.assertEqual(
            self._expr("event or timestamp or true or count()"),
            "or(events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), true, count())",
        )
        self.assertEqual(
            self._expr("event or not timestamp"),
            "or(events.event, not(toTimeZone(events.timestamp, %(hogql_val_0)s)))",
        )

    def test_comparisons(self):
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(self._expr("event == 'E'", context), "equals(events.event, %(hogql_val_0)s)")
        self.assertEqual(
            self._expr("event != 'E'", context),
            "notEquals(events.event, %(hogql_val_1)s)",
        )
        self.assertEqual(self._expr("event > 'E'", context), "greater(events.event, %(hogql_val_2)s)")
        self.assertEqual(
            self._expr("event >= 'E'", context),
            "greaterOrEquals(events.event, %(hogql_val_3)s)",
        )
        self.assertEqual(self._expr("event < 'E'", context), "less(events.event, %(hogql_val_4)s)")
        self.assertEqual(
            self._expr("event <= 'E'", context),
            "lessOrEquals(events.event, %(hogql_val_5)s)",
        )
        self.assertEqual(self._expr("event like 'E'", context), "like(events.event, %(hogql_val_6)s)")
        self.assertEqual(
            self._expr("event not like 'E'", context),
            "notLike(events.event, %(hogql_val_7)s)",
        )
        self.assertEqual(
            self._expr("event ilike 'E'", context),
            "ilike(events.event, %(hogql_val_8)s)",
        )
        self.assertEqual(
            self._expr("event not ilike 'E'", context),
            "notILike(events.event, %(hogql_val_9)s)",
        )
        self.assertEqual(self._expr("event in 'E'", context), "in(events.event, %(hogql_val_10)s)")
        self.assertEqual(
            self._expr("event not in 'E'", context),
            "notIn(events.event, %(hogql_val_11)s)",
        )
        self.assertEqual(self._expr("event ~ 'E'", context), "match(events.event, %(hogql_val_12)s)")
        self.assertEqual(self._expr("event =~ 'E'", context), "match(events.event, %(hogql_val_13)s)")
        self.assertEqual(
            self._expr("event !~ 'E'", context),
            "not(match(events.event, %(hogql_val_14)s))",
        )
        self.assertEqual(
            self._expr("event ~* 'E'", context),
            "match(events.event, concat('(?i)', %(hogql_val_15)s))",
        )
        self.assertEqual(
            self._expr("event =~* 'E'", context),
            "match(events.event, concat('(?i)', %(hogql_val_16)s))",
        )
        self.assertEqual(
            self._expr("event !~* 'E'", context),
            "not(match(events.event, concat('(?i)', %(hogql_val_17)s)))",
        )

    def test_comments(self):
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(self._expr("event -- something", context), "events.event")

    def test_values(self):
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(self._expr("event == 'E'", context), "equals(events.event, %(hogql_val_0)s)")
        self.assertEqual(context.values, {"hogql_val_0": "E"})
        self.assertEqual(
            self._expr("coalesce(4.2, 5, 'lol', 'hoo')", context),
            "coalesce(4.2, 5, %(hogql_val_1)s, %(hogql_val_2)s)",
        )
        self.assertEqual(
            context.values,
            {"hogql_val_0": "E", "hogql_val_1": "lol", "hogql_val_2": "hoo"},
        )

    def test_alias_keywords(self):
        self._assert_expr_error(
            "1 as team_id",
            '"team_id" cannot be an alias or identifier, as it\'s a reserved keyword',
        )
        self._assert_expr_error(
            "1 as true",
            '"true" cannot be an alias or identifier, as it\'s a reserved keyword',
        )
        self._assert_select_error(
            "select 1 as team_id from events",
            '"team_id" cannot be an alias or identifier, as it\'s a reserved keyword',
        )
        self.assertEqual(
            self._select("select 1 as `-- select team_id` from events"),
            f"SELECT 1 AS `-- select team_id` FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        # Some aliases are funny, but that's what the antlr syntax permits, and ClickHouse doesn't complain either
        self.assertEqual(
            self._expr("event makes little sense"),
            "((events.event AS makes) AS little) AS sense",
        )

    def test_case_when(self):
        self.assertEqual(self._expr("case when 1 then 2 else 3 end"), "if(1, 2, 3)")

    def test_case_when_many(self):
        self.assertEqual(
            self._expr("case when 1 then 2 when 3 then 4 else 5 end"),
            "multiIf(1, 2, 3, 4, 5)",
        )

    def test_case_when_case(self):
        self.assertEqual(
            self._expr("case 0 when 1 then 2 when 3 then 4 else 5 end"),
            "transform(0, [1, 3], [2, 4], 5)",
        )

    def test_select(self):
        self.assertEqual(self._select("select 1"), "SELECT 1 LIMIT 10000")
        self.assertEqual(self._select("select 1 + 2"), "SELECT plus(1, 2) LIMIT 10000")
        self.assertEqual(self._select("select 1 + 2, 3"), "SELECT plus(1, 2), 3 LIMIT 10000")
        self.assertEqual(
            self._select("select 1 + 2, 3 + 4 from events"),
            f"SELECT plus(1, 2), plus(3, 4) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_select_alias(self):
        # currently not supported!
        self.assertEqual(self._select("select 1 as b"), "SELECT 1 AS b LIMIT 10000")
        self.assertEqual(
            self._select("select 1 from events as e"),
            f"SELECT 1 FROM events AS e WHERE equals(e.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_select_from(self):
        self.assertEqual(
            self._select("select 1 from events"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self._assert_select_error("select 1 from other", 'Unknown table "other".')

    def test_select_from_placeholder(self):
        self.assertEqual(
            self._select(
                "select 1 from {placeholder}",
                placeholders={"placeholder": ast.Field(chain=["events"])},
            ),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        with self.assertRaises(HogQLException) as error_context:
            (
                self._select(
                    "select 1 from {placeholder}",
                    placeholders={
                        "placeholder": ast.CompareOperation(
                            left=ast.Constant(value=1),
                            right=ast.Constant(value=1),
                            op=ast.CompareOperationOp.Eq,
                        )
                    },
                ),
            )
        self.assertEqual(
            str(error_context.exception),
            "JoinExpr with table of type CompareOperation not supported",
        )

    def test_select_cross_join(self):
        self.assertEqual(
            self._select("select 1 from events cross join raw_groups"),
            f"SELECT 1 FROM events CROSS JOIN groups WHERE and(equals(groups.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 10000",
        )
        self.assertEqual(
            self._select("select 1 from events, raw_groups"),
            f"SELECT 1 FROM events CROSS JOIN groups WHERE and(equals(groups.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT 10000",
        )

    def test_select_array_join(self):
        self.assertEqual(
            self._select("select 1, a from events array join [1,2,3] as a"),
            f"SELECT 1, a FROM events ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            self._select("select 1, a from events left array join [1,2,3] as a"),
            f"SELECT 1, a FROM events LEFT ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            self._select("select 1, a from events inner array join [1,2,3] as a"),
            f"SELECT 1, a FROM events INNER ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_select_where(self):
        self.assertEqual(
            self._select("select 1 from events where 1 == 2"),
            f"SELECT 1 FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT 10000",
        )

    def test_select_having(self):
        self.assertEqual(
            self._select("select 1 from events having 1 == 2"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) HAVING 0 LIMIT 10000",
        )

    def test_select_prewhere(self):
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2 where 2 == 3"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT 10000",
        )

    def test_select_order_by(self):
        self.assertEqual(
            self._select("select event from events order by event"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event ASC LIMIT 10000",
        )
        self.assertEqual(
            self._select("select event from events order by event desc"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event DESC LIMIT 10000",
        )
        self.assertEqual(
            self._select("select event from events order by event desc, timestamp"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event DESC, toTimeZone(events.timestamp, %(hogql_val_0)s) ASC LIMIT 10000",
        )

    def test_select_limit(self):
        self.assertEqual(
            self._select("select event from events limit 10"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )
        self.assertEqual(
            self._select("select event from events limit 1000000"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            self._select("select event from events limit (select 100000000)"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT min2(10000, (SELECT 100000000))",
        )

        self.assertEqual(
            self._select("select event from events limit (select 100000000) with ties"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT min2(10000, (SELECT 100000000)) WITH TIES",
        )

    def test_select_offset(self):
        # Only the default limit if OFFSET is specified alone
        self.assertEqual(
            self._select("select event from events offset 10"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 10"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 0",
        )
        self.assertEqual(
            self._select("select event from events limit 10 with ties offset 0"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 WITH TIES OFFSET 0",
        )

    def test_select_limit_by(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 by 1,event"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 0 BY 1, events.event",
        )

    def test_select_group_by(self):
        self.assertEqual(
            self._select("select event from events group by event, timestamp"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s) LIMIT 10000",
        )

    def test_select_distinct(self):
        self.assertEqual(
            self._select("select distinct event from events group by event, timestamp"),
            f"SELECT DISTINCT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s) LIMIT 10000",
        )

    def test_select_subquery(self):
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp)"),
            f"SELECT event FROM (SELECT DISTINCT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s)) LIMIT 10000",
        )
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp) e"),
            f"SELECT e.event FROM (SELECT DISTINCT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s)) AS e LIMIT 10000",
        )

    def test_select_union_all(self):
        self.assertEqual(
            self._select("SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2"),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 UNION ALL SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT 10000",
        )
        self.assertEqual(
            self._select(
                "SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2 UNION ALL SELECT events.event FROM events WHERE 1 = 2"
            ),
            f"SELECT events.event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 UNION ALL SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT 10000 UNION ALL SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT 10000",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL (SELECT 1 UNION ALL SELECT 1) UNION ALL SELECT 1"),
            "SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1"),
            "SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000 UNION ALL SELECT 1 LIMIT 10000",
        )
        self.assertEqual(
            self._select("SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1)"),
            "SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1) LIMIT 10000",
        )

    def test_select_sample(self):
        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 1"),
            f"SELECT events.event FROM events SAMPLE 1 WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 0.1 OFFSET 1/10"),
            f"SELECT events.event FROM events SAMPLE 0.1 OFFSET 1/10 WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 2/78 OFFSET 999"),
            f"SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v2),
            )
            self.assertEqual(
                self._select(
                    "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id",
                    context,
                ),
                f"SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 INNER JOIN (SELECT argMax(person_distinct_id2.person_id, "
                f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 "
                f"WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
                f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi "
                f"ON equals(events.distinct_id, events__pdi.distinct_id) JOIN (SELECT person.id FROM person "
                f"WHERE and(equals(person.team_id, {self.team.pk}), ifNull(in(tuple(person.id, person.version), "
                f"(SELECT person.id, max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) "
                f"GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0))), 0)) "
                f"SETTINGS optimize_aggregation_in_order=1) AS persons ON equals(persons.id, events__pdi.person_id) "
                f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
            )

            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v2),
            )
            self.assertEqual(
                self._select(
                    "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id",
                    context,
                ),
                f"SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 INNER JOIN (SELECT argMax(person_distinct_id2.person_id, "
                f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 "
                f"WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
                f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi "
                f"ON equals(events.distinct_id, events__pdi.distinct_id) JOIN (SELECT person.id FROM person WHERE "
                f"and(equals(person.team_id, {self.team.pk}), ifNull(in(tuple(person.id, person.version), (SELECT person.id, "
                f"max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0))), 0)) SETTINGS optimize_aggregation_in_order=1) "
                f"AS persons SAMPLE 0.1 ON equals(persons.id, events__pdi.person_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v2),
            )
            expected = self._select(
                "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id",
                context,
            )
            self.assertEqual(
                expected,
                f"SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN (SELECT person.id FROM person WHERE "
                f"and(equals(person.team_id, {self.team.pk}), ifNull(in(tuple(person.id, person.version), (SELECT person.id, "
                f"max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0))), 0)) SETTINGS optimize_aggregation_in_order=1) "
                f"AS persons ON equals(persons.id, events.person_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
            )

            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v2),
            )
            expected = self._select(
                "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id",
                context,
            )
            self.assertEqual(
                expected,
                f"SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN (SELECT person.id FROM person WHERE "
                f"and(equals(person.team_id, {self.team.pk}), ifNull(in(tuple(person.id, person.version), (SELECT person.id, "
                f"max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0))), 0)) SETTINGS optimize_aggregation_in_order=1) "
                f"AS persons SAMPLE 0.1 ON equals(persons.id, events.person_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
            )

    def test_count_distinct(self):
        self.assertEqual(
            self._select("SELECT count(distinct event) FROM events"),
            f"SELECT count(DISTINCT events.event) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_count_star(self):
        self.assertEqual(
            self._select("SELECT count(*) FROM events"),
            f"SELECT count(*) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_count_if_distinct(self):
        self.assertEqual(
            self._select("SELECT countIf(distinct event, event like '%a%') FROM events"),
            f"SELECT countIf(DISTINCT events.event, like(events.event, %(hogql_val_0)s)) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_print_timezone(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=Database(None, WeekStartDay.SUNDAY),
        )
        context.database.events.fields["test_date"] = DateDatabaseField(name="test_date")  # type: ignore

        self.assertEqual(
            self._select(
                "SELECT now(), toDateTime(timestamp), toDate(test_date), toDateTime('2020-02-02') FROM events",
                context,
            ),
            f"SELECT now64(6, %(hogql_val_0)s), toDateTime(toTimeZone(events.timestamp, %(hogql_val_1)s), %(hogql_val_2)s), toDate(events.test_date, %(hogql_val_3)s), parseDateTime64BestEffortOrNull(%(hogql_val_4)s, 6, %(hogql_val_5)s) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            context.values,
            {
                "hogql_val_0": "UTC",
                "hogql_val_1": "UTC",
                "hogql_val_2": "UTC",
                "hogql_val_3": "UTC",
                "hogql_val_4": "2020-02-02",
                "hogql_val_5": "UTC",
            },
        )

    def test_print_timezone_custom(self):
        self.team.timezone = "Europe/Brussels"
        self.team.save()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        self.assertEqual(
            self._select(
                "SELECT now(), toDateTime(timestamp), toDateTime('2020-02-02') FROM events",
                context,
            ),
            f"SELECT now64(6, %(hogql_val_0)s), toDateTime(toTimeZone(events.timestamp, %(hogql_val_1)s), %(hogql_val_2)s), parseDateTime64BestEffortOrNull(%(hogql_val_3)s, 6, %(hogql_val_4)s) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )
        self.assertEqual(
            context.values,
            {
                "hogql_val_0": "Europe/Brussels",
                "hogql_val_1": "Europe/Brussels",
                "hogql_val_2": "Europe/Brussels",
                "hogql_val_3": "2020-02-02",
                "hogql_val_4": "Europe/Brussels",
            },
        )

    def test_print_timezone_gibberish(self):
        self.team.timezone = "Europe/PostHogLandia"
        self.team.save()

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        with self.assertRaises(HogQLException) as error_context:
            self._select(
                "SELECT now(), toDateTime(timestamp), toDateTime('2020-02-02') FROM events",
                context,
            )
        self.assertEqual(str(error_context.exception), "Unknown timezone: 'Europe/PostHogLandia'")

    def test_window_functions(self):
        self.assertEqual(
            self._select(
                "SELECT distinct_id, min(timestamp) over win1 as timestamp FROM events WINDOW win1 as (PARTITION by distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            ),
            f"SELECT events.distinct_id, min(toTimeZone(events.timestamp, %(hogql_val_0)s)) OVER win1 AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) LIMIT 10000",
        )

    def test_window_functions_with_window(self):
        self.assertEqual(
            self._select(
                "SELECT distinct_id, min(timestamp) over win1 as timestamp FROM events WINDOW win1 as (PARTITION by distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            ),
            f"SELECT events.distinct_id, min(toTimeZone(events.timestamp, %(hogql_val_0)s)) OVER win1 AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) LIMIT 10000",
        )

    def test_nullish_concat(self):
        self.assertEqual(
            self._expr("concat(null, 'a', 3, toString(4), toString(NULL))"),
            f"concat('', %(hogql_val_0)s, toString(3), toString(4), '')",
        )

    def test_concat_pipes(self):
        self.assertEqual(
            self._expr("'a' || 'b' || 3 || timestamp"),
            f"concat(%(hogql_val_0)s, %(hogql_val_1)s, toString(3), ifNull(toString(toTimeZone(events.timestamp, %(hogql_val_2)s)), ''))",
        )

    def test_to_start_of_week_gets_mode(self):
        # It's important we use ints and not WeekStartDay here, because it's the former that's actually in the DB
        default_week_context = HogQLContext(team_id=self.team.pk, database=Database(None, None))
        sunday_week_context = HogQLContext(team_id=self.team.pk, database=Database(None, 0))  # 0 == WeekStartDay.SUNDAY
        monday_week_context = HogQLContext(team_id=self.team.pk, database=Database(None, 1))  # 1 == WeekStartDay.MONDAY

        self.assertEqual(
            self._expr("toStartOfWeek(timestamp)", default_week_context),  # Sunday is the default
            f"toStartOfWeek(toTimeZone(events.timestamp, %(hogql_val_0)s), 0)",
        )
        self.assertEqual(
            self._expr("toStartOfWeek(timestamp)"),  # Sunday is the default
            f"toStartOfWeek(toTimeZone(events.timestamp, %(hogql_val_0)s), 0)",
        )
        self.assertEqual(
            self._expr("toStartOfWeek(timestamp)", sunday_week_context),
            f"toStartOfWeek(toTimeZone(events.timestamp, %(hogql_val_0)s), 0)",
        )
        self.assertEqual(
            self._expr("toStartOfWeek(timestamp)", monday_week_context),
            f"toStartOfWeek(toTimeZone(events.timestamp, %(hogql_val_0)s), 3)",
        )

    def test_functions_expecting_datetime_arg(self):
        self.assertEqual(
            self._expr("tumble(toDateTime('2023-06-12'), toIntervalDay('1'))"),
            f"tumble(assumeNotNull(toDateTime(parseDateTime64BestEffortOrNull(%(hogql_val_0)s, 6, %(hogql_val_1)s))), toIntervalDay(%(hogql_val_2)s))",
        )
        self.assertEqual(
            self._expr("tumble(now(), toIntervalDay('1'))"),
            f"tumble(toDateTime(now64(6, %(hogql_val_0)s), 'UTC'), toIntervalDay(%(hogql_val_1)s))",
        )
        self.assertEqual(
            self._expr("tumble(parseDateTime('2021-01-04+23:00:00', '%Y-%m-%d+%H:%i:%s'), toIntervalDay('1'))"),
            f"tumble(assumeNotNull(toDateTime(parseDateTimeOrNull(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s))), toIntervalDay(%(hogql_val_3)s))",
        )
        self.assertEqual(
            self._expr("tumble(parseDateTimeBestEffort('23/10/2020 12:12:57'), toIntervalDay('1'))"),
            f"tumble(assumeNotNull(toDateTime(parseDateTime64BestEffortOrNull(%(hogql_val_0)s, 6, %(hogql_val_1)s))), toIntervalDay(%(hogql_val_2)s))",
        )
        self.assertEqual(
            self._select("SELECT tumble(timestamp, toIntervalDay('1')) FROM events"),
            f"SELECT tumble(toDateTime(toTimeZone(events.timestamp, %(hogql_val_0)s), 'UTC'), toIntervalDay(%(hogql_val_1)s)) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000",
        )

    def test_field_nullable_equals(self):
        generated_sql_statements = self._select(
            "SELECT min_first_timestamp = toStartOfMonth(now()), now() = now(), 1 = now(), now() = 1, 1 = 1, click_count = 1, 1 = click_count, click_count = keypress_count, click_count = null, null = click_count FROM session_replay_events"
        )
        assert generated_sql_statements == (
            f"SELECT "
            # min_first_timestamp = toStartOfMonth(now())
            # (the return of toStartOfMonth() is treated as "potentially nullable" since we yet have full typing support)
            f"ifNull(equals(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s), toStartOfMonth(now64(6, %(hogql_val_1)s))), "
            f"isNull(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s)) and isNull(toStartOfMonth(now64(6, %(hogql_val_1)s)))), "
            # now() = now() (also two nullable fields)
            f"ifNull(equals(now64(6, %(hogql_val_2)s), now64(6, %(hogql_val_3)s)), isNull(now64(6, %(hogql_val_2)s)) and isNull(now64(6, %(hogql_val_3)s))), "
            # 1 = now()
            f"ifNull(equals(1, now64(6, %(hogql_val_4)s)), 0), "
            # now() = 1
            f"ifNull(equals(now64(6, %(hogql_val_5)s), 1), 0), "
            # 1 = 1
            f"1, "
            # click_count = 1
            f"ifNull(equals(session_replay_events.click_count, 1), 0), "
            # 1 = click_count
            f"ifNull(equals(1, session_replay_events.click_count), 0), "
            # click_count = keypress_count
            f"ifNull(equals(session_replay_events.click_count, session_replay_events.keypress_count), isNull(session_replay_events.click_count) and isNull(session_replay_events.keypress_count)), "
            # click_count = null
            f"isNull(session_replay_events.click_count), "
            # null = click_count
            f"isNull(session_replay_events.click_count) "
            # ...
            f"FROM (SELECT session_replay_events.min_first_timestamp AS min_first_timestamp, sum(session_replay_events.click_count) AS click_count, sum(session_replay_events.keypress_count) AS keypress_count FROM session_replay_events WHERE equals(session_replay_events.team_id, {self.team.pk}) GROUP BY session_replay_events.min_first_timestamp) AS session_replay_events LIMIT 10000"
        )

    def test_field_nullable_not_equals(self):
        generated_sql = self._select(
            "SELECT min_first_timestamp != toStartOfMonth(now()), now() != now(), 1 != now(), now() != 1, 1 != 1, "
            "click_count != 1, 1 != click_count, click_count != keypress_count, click_count != null, null != click_count "
            "FROM session_replay_events"
        )
        assert generated_sql == (
            f"SELECT "
            # min_first_timestamp = toStartOfMonth(now())
            # (the return of toStartOfMonth() is treated as "potentially nullable" since we yet have full typing support)
            f"ifNull(notEquals(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s), toStartOfMonth(now64(6, %(hogql_val_1)s))), "
            f"isNotNull(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s)) or isNotNull(toStartOfMonth(now64(6, %(hogql_val_1)s)))), "
            # now() = now() (also two nullable fields)
            f"ifNull(notEquals(now64(6, %(hogql_val_2)s), now64(6, %(hogql_val_3)s)), isNotNull(now64(6, %(hogql_val_2)s)) or isNotNull(now64(6, %(hogql_val_3)s))), "
            # 1 = now()
            f"ifNull(notEquals(1, now64(6, %(hogql_val_4)s)), 1), "
            # now() = 1
            f"ifNull(notEquals(now64(6, %(hogql_val_5)s), 1), 1), "
            # 1 = 1
            f"0, "
            # click_count = 1
            f"ifNull(notEquals(session_replay_events.click_count, 1), 1), "
            # 1 = click_count
            f"ifNull(notEquals(1, session_replay_events.click_count), 1), "
            # click_count = keypress_count
            f"ifNull(notEquals(session_replay_events.click_count, session_replay_events.keypress_count), isNotNull(session_replay_events.click_count) or isNotNull(session_replay_events.keypress_count)), "
            # click_count = null
            f"isNotNull(session_replay_events.click_count), "
            # null = click_count
            f"isNotNull(session_replay_events.click_count) "
            # ...
            f"FROM (SELECT session_replay_events.min_first_timestamp AS min_first_timestamp, sum(session_replay_events.click_count) AS click_count, sum(session_replay_events.keypress_count) AS keypress_count FROM session_replay_events WHERE equals(session_replay_events.team_id, {self.team.pk}) GROUP BY session_replay_events.min_first_timestamp) AS session_replay_events LIMIT 10000"
        )

    def test_print_global_settings(self):
        query = parse_select("SELECT 1 FROM events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1",
        )

    def test_print_query_level_settings(self):
        query = parse_select("SELECT 1 FROM events")
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 SETTINGS optimize_aggregation_in_order=1",
        )

    def test_print_both_settings(self):
        query = parse_select("SELECT 1 FROM events")
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000 SETTINGS optimize_aggregation_in_order=1, readonly=2, max_execution_time=10, allow_experimental_object_type=1",
        )

    def test_pretty_print(self):
        printed = self._pretty("SELECT 1, event FROM events")
        self.assertEqual(
            printed,
            f"SELECT\n    1,\n    event\nFROM\n    events\nLIMIT 10000",
        )

    def test_pretty_print_subquery(self):
        printed = self._pretty("SELECT 1, event FROM (select 1, event from events)")
        self.assertEqual(
            printed,
            f"""SELECT\n    1,\n    event\nFROM\n    (SELECT\n        1,\n        event\n    FROM\n        events)\nLIMIT 10000""",
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_large_pretty_print(self):
        printed = self._pretty(
            """
            SELECT
                groupArray(start_of_period) AS date,
                groupArray(counts) AS total,
                status
            FROM
                (SELECT
                    if(equals(status, 'dormant'), negate(sum(counts)), negate(negate(sum(counts)))) AS counts,
                    start_of_period,
                    status
                FROM
                    (SELECT
                        periods.start_of_period AS start_of_period,
                        0 AS counts,
                        status
                    FROM
                        (SELECT
                            minus(dateTrunc('day', assumeNotNull(toDateTime('2023-10-19 23:59:59'))), toIntervalDay(number)) AS start_of_period
                        FROM
                            numbers(dateDiff('day', dateTrunc('day', assumeNotNull(toDateTime('2023-09-19 00:00:00'))), dateTrunc('day', plus(assumeNotNull(toDateTime('2023-10-19 23:59:59')), toIntervalDay(1))))) AS numbers) AS periods CROSS JOIN (SELECT
                            status
                        FROM
                            (SELECT
                                1)
                        ARRAY JOIN ['new', 'returning', 'resurrecting', 'dormant'] AS status) AS sec
                    ORDER BY
                        status ASC,
                        start_of_period ASC
                    UNION ALL
                    SELECT
                        start_of_period,
                        count(DISTINCT person_id) AS counts,
                        status
                    FROM
                        (SELECT
                            events.person.id AS person_id,
                            min(events.person.created_at) AS created_at,
                            arraySort(groupUniqArray(dateTrunc('day', events.timestamp))) AS all_activity,
                            arrayPopBack(arrayPushFront(all_activity, dateTrunc('day', created_at))) AS previous_activity,
                            arrayPopFront(arrayPushBack(all_activity, dateTrunc('day', toDateTime('1970-01-01 00:00:00')))) AS following_activity,
                            arrayMap((previous, current, index) -> if(equals(previous, current), 'new', if(and(equals(minus(current, toIntervalDay(1)), previous), notEquals(index, 1)), 'returning', 'resurrecting')), previous_activity, all_activity, arrayEnumerate(all_activity)) AS initial_status,
                            arrayMap((current, next) -> if(equals(plus(current, toIntervalDay(1)), next), '', 'dormant'), all_activity, following_activity) AS dormant_status,
                            arrayMap(x -> plus(x, toIntervalDay(1)), arrayFilter((current, is_dormant) -> equals(is_dormant, 'dormant'), all_activity, dormant_status)) AS dormant_periods,
                            arrayMap(x -> 'dormant', dormant_periods) AS dormant_label,
                            arrayConcat(arrayZip(all_activity, initial_status), arrayZip(dormant_periods, dormant_label)) AS temp_concat,
                            arrayJoin(temp_concat) AS period_status_pairs,
                            period_status_pairs.1 AS start_of_period,
                            period_status_pairs.2 AS status
                        FROM
                            events
                        WHERE
                            and(greaterOrEquals(timestamp, minus(dateTrunc('day', assumeNotNull(toDateTime('2023-09-19 00:00:00'))), toIntervalDay(1))), less(timestamp, plus(dateTrunc('day', assumeNotNull(toDateTime('2023-10-19 23:59:59'))), toIntervalDay(1))), equals(event, '$pageview'))
                        GROUP BY
                            person_id)
                    GROUP BY
                        start_of_period,
                        status)
                WHERE
                    and(lessOrEquals(start_of_period, dateTrunc('day', assumeNotNull(toDateTime('2023-10-19 23:59:59')))), greaterOrEquals(start_of_period, dateTrunc('day', assumeNotNull(toDateTime('2023-09-19 00:00:00')))))
                GROUP BY
                    start_of_period,
                    status
                ORDER BY
                    start_of_period ASC)
            GROUP BY
                status
            LIMIT 10000
        """
        )
        assert printed == self.snapshot
