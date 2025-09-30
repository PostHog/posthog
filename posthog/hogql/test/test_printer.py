import json
from collections.abc import Mapping
from typing import Any, Literal, Optional, cast

import pytest
from posthog.test.base import APIBaseTest, BaseTest, _create_event, clean_varying_query_parts, materialized
from unittest import mock
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    HogQLQueryModifiers,
    MaterializationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    PropertyGroupsMode,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings, HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DateDatabaseField, StringDatabaseField
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_ast, print_prepared_ast, to_printed_hogql
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import PropertyDefinition
from posthog.models.cohort.cohort import Cohort
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DICTIONARY_NAME
from posthog.models.team.team import WeekStartDay
from posthog.settings.data_stores import CLICKHOUSE_DATABASE
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable


class TestPrinter(BaseTest):
    maxDiff = None

    # Helper to always translate HogQL with a blank context
    def _expr(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ) -> str:
        node = parse_expr(query)
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect=dialect, stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect=dialect,
            stack=[prepared_select_query],
        )

    # Helper to always translate HogQL with a blank context,
    def _select(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        placeholders: Optional[dict[str, ast.Expr]] = None,
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
        with self.assertRaises(ExposedHogQLError) as context:
            self._expr(expr, None, dialect)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _assert_select_error(self, statement, expected_error):
        with self.assertRaises(ExposedHogQLError) as context:
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
        repsponse = to_printed_hogql(expr, self.team)
        self.assertEqual(
            repsponse, f"SELECT\n    plus(1, 2),\n    3\nFROM\n    events\nLIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_union_distinct(self):
        expr = parse_select("""select 1 as id union distinct select 2 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            f"SELECT\n    1 AS id\nLIMIT 50000\nUNION DISTINCT\nSELECT\n    2 AS id\nLIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_intersect(self):
        expr = parse_select("""select 1 as id intersect select 2 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            f"SELECT\n    1 AS id\nLIMIT 50000\nINTERSECT\nSELECT\n    2 AS id\nLIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_intersect_distinct(self):
        expr = parse_select("""select 1 as id intersect distinct select 2 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            f"SELECT\n    1 AS id\nLIMIT 50000\nINTERSECT DISTINCT\nSELECT\n    2 AS id\nLIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_except(self):
        expr = parse_select("""select 1 as id except select 2 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            f"SELECT\n    1 AS id\nLIMIT 50000\nEXCEPT\nSELECT\n    2 AS id\nLIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    # these share the same priority, should stay in order
    def test_except_and_union(self):
        expr = parse_select("""select 1 as id except select 2 as id union all select 3 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            (
                "SELECT\n"
                "    1 AS id\n"
                "LIMIT 50000\n"
                "EXCEPT\n"
                "SELECT\n"
                "    2 AS id\n"
                "LIMIT 50000\n"
                "UNION ALL\n"
                "SELECT\n"
                "    3 AS id\n"
                "LIMIT 50000"
            ),
        )

    def test_union_and_except(self):
        expr = parse_select("""select 1 as id union all select 2 as id except select 3 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            (
                "SELECT\n"
                "    1 AS id\n"
                "LIMIT 50000\n"
                "UNION ALL\n"
                "SELECT\n"
                "    2 AS id\n"
                "LIMIT 50000\n"
                "EXCEPT\n"
                "SELECT\n"
                "    3 AS id\n"
                "LIMIT 50000"
            ),
        )

    def test_intersect3(self):
        expr = parse_select("""select 1 as id intersect select 2 as id intersect select 3 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            "SELECT\n"
            "    1 AS id\n"
            "LIMIT 50000\n"
            "INTERSECT\n"
            "SELECT\n"
            "    2 AS id\n"
            "LIMIT 50000\n"
            "INTERSECT\n"
            "SELECT\n"
            "    3 AS id\n"
            "LIMIT 50000",
        )

    def test_union3(self):
        expr = parse_select("""select 1 as id union all select 2 as id union all select 3 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            "SELECT\n"
            "    1 AS id\n"
            "LIMIT 50000\n"
            "UNION ALL\n"
            "SELECT\n"
            "    2 AS id\n"
            "LIMIT 50000\n"
            "UNION ALL\n"
            "SELECT\n"
            "    3 AS id\n"
            "LIMIT 50000",
        )

    def test_intersect_and_union_parens(self):
        expr = parse_select("""select 1 as id intersect (select 2 as id union all select 3 as id)""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            "SELECT\n    1 AS id\nLIMIT 50000\nINTERSECT\n(SELECT\n    2 AS id\nUNION ALL\nSELECT\n    3 AS id)",
        )

    # INTERSECT has higher priority than union
    def test_intersect_and_union(self):
        expr = parse_select("""select 1 as id union all select 2 as id intersect select 3 as id""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            (
                "SELECT\n"
                "    1 AS id\n"
                "LIMIT 50000\n"
                "UNION ALL\n"
                "SELECT\n"
                "    2 AS id\n"
                "LIMIT 50000\n"
                "INTERSECT\n"
                "SELECT\n"
                "    3 AS id\n"
                "LIMIT 50000"
            ),
        )

    def test_print_to_string(self):
        assert str(parse_select("select 1 + 2, 3 from events")) == "sql(SELECT plus(1, 2), 3 FROM events)"
        assert str(parse_expr("1 + 2")) == "sql(plus(1, 2))"
        assert str(parse_expr("unknown_field")) == "sql(unknown_field)"

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

        self.assertEqual(self._expr("[1,2,3]?.[1]", dialect="hogql"), "[1, 2, 3]?.[1]")
        self.assertEqual(self._expr("[1,2,3]?.[1]", dialect="clickhouse"), "[1, 2, 3][1]")  # no nullish

    def test_tuples(self):
        self.assertEqual(self._expr("(1,2)"), "tuple(1, 2)")
        self.assertEqual(self._expr("(1,2,[])"), "tuple(1, 2, [])")

    def test_tuple_access(self):
        self.assertEqual(self._expr("(1,2)?.2", dialect="hogql"), "tuple(1, 2)?.2")
        self.assertEqual(self._expr("(1,2)?.2", dialect="clickhouse"), "tuple(1, 2).2")  # no nullish

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
                modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED),
            )
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person_props, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
            )
            context = HogQLContext(team_id=self.team.pk)
            self.assertEqual(
                self._expr("person.properties.bla", context),
                "events__person.properties___bla",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            context = HogQLContext(
                team_id=self.team.pk,
                within_non_hogql_query=True,
                modifiers=HogQLQueryModifiers(
                    personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                ),
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
            "mismatched input",
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

        context = HogQLContext(team_id=self.team.pk)
        materialize("events", "withmat")
        self.assertEqual(
            self._expr("properties.withmat.json.yet", context),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(nullIf(nullIf(events.mat_withmat, ''), 'null'), %(hogql_val_0)s, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
        )
        self.assertEqual(context.values, {"hogql_val_0": "json", "hogql_val_1": "yet"})

        context = HogQLContext(team_id=self.team.pk)
        materialize("events", "withmat_nullable", is_nullable=True)
        self.assertEqual(
            self._expr("properties.withmat_nullable.json.yet", context),
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.mat_withmat_nullable, %(hogql_val_0)s, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
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

        materialize("events", "nullable_property", is_nullable=True)
        self.assertEqual(
            self._expr("properties['nullable_property']"),
            "events.mat_nullable_property",
        )

    def test_property_groups(self):
        context = HogQLContext(
            team_id=self.team.pk,
            modifiers=HogQLQueryModifiers(
                materializationMode=MaterializationMode.AUTO,
                propertyGroupsMode=PropertyGroupsMode.ENABLED,
            ),
        )

        self.assertEqual(
            self._expr("properties['foo']", context),
            "has(events.properties_group_custom, %(hogql_val_0)s) ? events.properties_group_custom[%(hogql_val_0)s] : null",
        )
        self.assertEqual(context.values["hogql_val_0"], "foo")

        with materialized("events", "foo"):
            # Properties that are materialized as columns should take precedence over the values in the group's map
            # column.
            self.assertEqual(
                self._expr("properties['foo']", context),
                "nullIf(nullIf(events.mat_foo, ''), 'null')",
            )

    def test_property_groups_person_properties(self):
        context = HogQLContext(
            team_id=self.team.pk,
            modifiers=HogQLQueryModifiers(
                materializationMode=MaterializationMode.AUTO,
                propertyGroupsMode=PropertyGroupsMode.ENABLED,
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
        )

        self.assertEqual(
            self._expr("person.properties['foo']", context),
            "has(events.person_properties_map_custom, %(hogql_val_0)s) ? events.person_properties_map_custom[%(hogql_val_0)s] : null",
        )
        self.assertEqual(context.values["hogql_val_0"], "foo")

    def _test_property_group_comparison(
        self,
        input_expression: str,
        expected_optimized_query: str | None,
        expected_context_values: Mapping[str, Any] | None = None,
        expected_skip_indexes_used: set[str] | None = None,
    ) -> None:
        def build_context(property_groups_mode: PropertyGroupsMode) -> HogQLContext:
            return HogQLContext(
                team_id=self.team.pk,
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    propertyGroupsMode=property_groups_mode,
                ),
            )

        context = build_context(PropertyGroupsMode.OPTIMIZED)
        printed_expr = self._expr(input_expression, context)
        if expected_optimized_query is not None:
            self.assertEqual(printed_expr, expected_optimized_query)
        else:
            unoptimized_context = build_context(PropertyGroupsMode.ENABLED)
            unoptimized_expr = self._expr(input_expression, unoptimized_context)
            # XXX: The placeholders used in the printed expression can vary between the direct and optimized variants,
            # so we string format the context values back into the expression template. This isn't necessarily going to
            # yield a valid ClickHouse expression, but it should generally be good enough to ensure the two expressions
            # are the same.
            self.assertEqual(printed_expr % context.values, unoptimized_expr % unoptimized_context.values)

        if expected_context_values is not None:
            self.assertDictContainsSubset(expected_context_values, context.values)

        if expected_skip_indexes_used is not None:
            # The table needs some data to be able get a `EXPLAIN` result that includes index information -- otherwise
            # the query is optimized to read from `NullSource` which doesn't do us much good here...
            for _ in range(10):
                _create_event(team=self.team, distinct_id="distinct_id", event="event")

            def _find_node(node, condition):
                """Find the first node in a query plan meeting a given condition (using depth-first search.)"""
                if condition(node):
                    return node
                else:
                    for child in node.get("Plans", []):
                        result = _find_node(child, condition)
                        if result is not None:
                            return result

            [[raw_explain_result]] = sync_execute(
                f"EXPLAIN indexes = 1, json = 1 SELECT count() FROM events WHERE {printed_expr}",
                context.values,
            )
            read_from_merge_tree_step = _find_node(
                json.loads(raw_explain_result)[0]["Plan"],
                condition=lambda node: node["Node Type"] == "ReadFromMergeTree",
            )
            self.assertTrue(
                expected_skip_indexes_used.issubset(
                    {index["Name"] for index in read_from_merge_tree_step.get("Indexes", []) if index["Type"] == "Skip"}
                ),
            )

    def test_property_groups_optimized_basic_equality_comparisons(self) -> None:
        # Comparing against a (non-empty) string value lets us avoid checking if the key exists or not, and lets us use
        # the bloom filter indices on both keys and values to optimize the comparison operation.
        self._test_property_group_comparison(
            "properties.key = 'value' as eq",
            "equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s) AS eq",
            {"hogql_val_0": "key", "hogql_val_1": "value"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "'value' = properties.key as eq",
            "equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s) AS eq",
            {"hogql_val_0": "key", "hogql_val_1": "value"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "equals(properties.key, 'value') as eq",
            "equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s) AS eq",
            {"hogql_val_0": "key", "hogql_val_1": "value"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )

        # Don't optimize comparisons to types that require non-trivial type conversions.
        self._test_property_group_comparison("properties.key = 1", None)

        # TODO: We'll want to eventually support this type of expression where the right hand side is a non-``Nullable``
        # value, since this would allow expressions that only reference constant values to also use the appropriate
        # index, but for right now we only want to optimize comparisons to constant values directly for simplicity.
        self._test_property_group_comparison("properties.key = lower('value')", None)

        # The opposite case as above: ``Nullable`` values should _not_ be optimized (because we don't know which
        # optimization to apply).
        self._test_property_group_comparison("properties.key = nullIf('a', 'a')", None)

        # ... unless we can distinguish ``Nullable(Nothing)`` from ``Nullable(*)`` -- this _could_ be safely optimized.
        self._test_property_group_comparison("properties.key = lower(NULL)", None)

    def test_property_groups_optimized_boolean_equality_comparisons(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="is_boolean", property_type="Boolean", type=PropertyDefinition.Type.EVENT
        )

        self._test_property_group_comparison(
            "properties.is_boolean = true",
            "equals(events.properties_group_custom[%(hogql_val_0)s], 'true')",
            {"hogql_val_0": "is_boolean"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )

        self._test_property_group_comparison(
            "properties.is_boolean = false",
            "equals(events.properties_group_custom[%(hogql_val_0)s], 'false')",
            {"hogql_val_0": "is_boolean"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )

        # Don't try to optimize not equals comparisons: NULL handling here is tricky, and we wouldn't get any benefit
        # from using the indexes anyway.
        self._test_property_group_comparison("properties.is_boolean != true", None, expected_skip_indexes_used=set())
        self._test_property_group_comparison("properties.is_boolean != false", None, expected_skip_indexes_used=set())

    def test_property_groups_optimized_empty_string_equality_comparisons(self) -> None:
        # Keys that don't exist in a map return default values for the type -- in our case empty strings -- so we need
        # to check whether or not the key exists in the map *and* compare the value in the map is the empty string or
        # not. We can still utilize the bloom filter index on keys, but the empty string isn't stored in the bloom
        # filter so it won't be used here.
        self._test_property_group_comparison(
            "properties.key = '' as eq",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s)) AS eq",
            {"hogql_val_0": "key", "hogql_val_1": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )
        self._test_property_group_comparison(
            "equals(properties.key, '') as eq",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s)) AS eq",
            {"hogql_val_0": "key", "hogql_val_1": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )

    def test_property_groups_optimized_null_comparisons(self) -> None:
        # NOT NULL comparisons should check to see if the key exists within the map (and should use the bloom filter to
        # optimize the check), but do not need to load the values subcolumn.
        self._test_property_group_comparison(
            "properties.key is not null as p",
            "has(events.properties_group_custom, %(hogql_val_0)s) AS p",
            {"hogql_val_0": "key"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )
        self._test_property_group_comparison(
            "properties.key != null as p",
            "has(events.properties_group_custom, %(hogql_val_0)s) AS p",
            {"hogql_val_0": "key"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )
        self._test_property_group_comparison(
            "isNotNull(properties.key) as p",
            "has(events.properties_group_custom, %(hogql_val_0)s) AS p",
            {"hogql_val_0": "key"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )

        # NULL comparisons don't really benefit from the bloom filter index like NOT NULL comparisons do, but like
        # above, only need to check the keys subcolumn and not the values subcolumn.
        self._test_property_group_comparison(
            "properties.key is null as p",
            "not(has(events.properties_group_custom, %(hogql_val_0)s)) AS p",
            {"hogql_val_0": "key"},
        )
        self._test_property_group_comparison(
            "properties.key = null as p",
            "not(has(events.properties_group_custom, %(hogql_val_0)s)) AS p",
            {"hogql_val_0": "key"},
        )
        self._test_property_group_comparison(
            "isNull(properties.key) as p",
            "not(has(events.properties_group_custom, %(hogql_val_0)s)) AS p",
            {"hogql_val_0": "key"},
        )

    def test_property_groups_optimized_has(self) -> None:
        self._test_property_group_comparison(
            "JSONHas(properties, 'key') as j",
            "has(events.properties_group_custom, %(hogql_val_0)s) AS j",
            {"hogql_val_0": "key"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )

        # TODO: Chained operations/path traversal could be optimized further, but is left alone for now.
        self._test_property_group_comparison("JSONHas(properties, 'foo', 'bar')", None)

        with materialized("events", "key"):
            self._test_property_group_comparison(
                "JSONHas(properties, 'key') as j",
                "has(events.properties_group_custom, %(hogql_val_0)s) AS j",
                {"hogql_val_0": "key"},
                expected_skip_indexes_used={"properties_group_custom_keys_bf"},
            )

    def test_property_groups_optimized_in_comparisons(self) -> None:
        # The IN operator works much like equality when the right hand side of the expression is all constants. Like
        # equality, it also needs to handle the empty string special case.
        self._test_property_group_comparison(
            "properties.key IN ('a', 'b')",
            "in(events.properties_group_custom[%(hogql_val_0)s], tuple(%(hogql_val_1)s, %(hogql_val_2)s))",
            {"hogql_val_0": "key", "hogql_val_1": "a", "hogql_val_2": "b"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN 'a'",  # strange, but syntactically valid
            "in(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s)",
            {"hogql_val_0": "key", "hogql_val_1": "a"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN ('a', 'b', '')",
            (
                "or("
                "in(events.properties_group_custom[%(hogql_val_0)s], tuple(%(hogql_val_1)s, %(hogql_val_2)s)), "
                "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_3)s))"
                ")"
            ),
            {"hogql_val_0": "key", "hogql_val_1": "a", "hogql_val_2": "b", "hogql_val_3": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN ''",  # strange, but syntactically valid
            "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s))",
            {"hogql_val_0": "key", "hogql_val_1": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )

        # NULL values are never equal. While this differs from the behavior of the equality operator above, it is
        # consistent with how ClickHouse treats these values:
        # https://clickhouse.com/docs/en/sql-reference/operators/in#null-processing
        self._test_property_group_comparison("properties.key in NULL", "0")
        self._test_property_group_comparison("properties.key in (NULL)", "0")
        self._test_property_group_comparison("properties.key in (NULL, NULL, NULL)", "0")
        self._test_property_group_comparison(
            "properties.key IN ('a', 'b', NULL)",
            "in(events.properties_group_custom[%(hogql_val_0)s], tuple(%(hogql_val_1)s, %(hogql_val_2)s))",
            {"hogql_val_0": "key", "hogql_val_1": "a", "hogql_val_2": "b"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN ('', NULL)",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s))",
            {"hogql_val_0": "key", "hogql_val_1": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
        )

        # Don't optimize comparisons to types that require additional type conversions.
        self._test_property_group_comparison("properties.key in true", None)
        self._test_property_group_comparison("properties.key in (true, false)", None)
        self._test_property_group_comparison("properties.key in 1", None)
        self._test_property_group_comparison("properties.key in (1, 2, 3)", None)

        # Only direct constant comparison is supported for now -- see above.
        self._test_property_group_comparison("properties.key in lower('value')", None)
        self._test_property_group_comparison("properties.key in (lower('a'), lower('b'))", None)

    def test_property_groups_select_with_aliases(self):
        def build_context(property_groups_mode: PropertyGroupsMode) -> HogQLContext:
            return HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    propertyGroupsMode=property_groups_mode,
                ),
            )

        parsed = parse_select("SELECT properties.file_type AS ft FROM events WHERE ft = 'image/svg'")
        printed = print_ast(parsed, build_context(PropertyGroupsMode.OPTIMIZED), dialect="clickhouse")
        assert printed == (
            "SELECT has(events.properties_group_custom, %(hogql_val_0)s) ? events.properties_group_custom[%(hogql_val_0)s] : null AS ft "
            "FROM events "
            f"WHERE and(equals(events.team_id, {self.team.pk}), equals(events.properties_group_custom[%(hogql_val_1)s], %(hogql_val_2)s)) "
            "LIMIT 50000"
        )

        # TODO: Ideally we'd be able to optimize queries that compare aliases, but this is a bit tricky since we need
        # the ability to resolve the field back to the aliased expression (if one exists) to determine whether or not
        # the condition can be optimized (and possibly just inline the aliased value to make things easier for the
        # analyzer.) Until then, this should just use the direct (simple) property group access method.
        parsed = parse_select("SELECT properties.file_type AS ft, 'image/svg' as ft2 FROM events WHERE ft = ft2")
        assert print_ast(parsed, build_context(PropertyGroupsMode.OPTIMIZED), dialect="clickhouse") == print_ast(
            parsed, build_context(PropertyGroupsMode.ENABLED), dialect="clickhouse"
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
        self.assertEqual(self._expr("toInt('1')", context), "accurateCastOrNull(%(hogql_val_0)s, %(hogql_val_1)s)")
        self.assertEqual(self._expr("toFloat('1.3')", context), "accurateCastOrNull(%(hogql_val_2)s, %(hogql_val_3)s)")
        self.assertEqual(
            self._expr("toUUID('470f9b15-ff43-402a-af9f-2ed7c526a6cf')", context),
            "accurateCastOrNull(%(hogql_val_4)s, %(hogql_val_5)s)",
        )
        self.assertEqual(
            self._expr("toDecimal('3.14', 2)", context), "accurateCastOrNull(%(hogql_val_6)s, %(hogql_val_7)s)"
        )
        self.assertEqual(self._expr("quantile(0.95)( event )"), "quantile(0.95)(events.event)")

        self.assertEqual(self._expr("groupArraySample(5)(event)"), "groupArraySample(5)(events.event)")
        self.assertEqual(self._expr("groupArraySample(5, 123456)(event)"), "groupArraySample(5, 123456)(events.event)")
        self.assertEqual(
            self._expr("groupArraySampleIf(5)(event, event is not null)"),
            "groupArraySampleIf(5)(events.event, isNotNull(events.event))",
        )
        self.assertEqual(
            self._expr("groupArraySampleIf(5, 123456)(event, event is not null)"),
            "groupArraySampleIf(5, 123456)(events.event, isNotNull(events.event))",
        )

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
            "Aggregation 'quantile' expects 1 parameter, found 0",
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
        self.assertEqual(  # does not error through subqueries
            "avg((select avg(properties.bla) from events))",
            "avg((select avg(properties.bla) from events))",
        )
        self._assert_expr_error("person.chipotle", "Field not found: chipotle")
        self._assert_expr_error("properties.0", "SQL indexes start from one, not from zero. E.g: array.1")
        self._assert_expr_error(
            "properties.id.0",
            "SQL indexes start from one, not from zero. E.g: array.1",
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
        self._assert_expr_error("())", "mismatched input ')' expecting '->'")
        self._assert_expr_error("(3 57", "no viable alternative at input '(3 57'")
        self._assert_expr_error("select query from events", "mismatched input 'query' expecting <EOF>")
        self._assert_expr_error("this makes little sense", "mismatched input 'makes' expecting <EOF>")
        self._assert_expr_error("1;2", "mismatched input ';' expecting <EOF>")
        self._assert_expr_error("b.a(bla)", "You can only call simple functions in HogQL, not expressions")
        self._assert_expr_error("a -> { print(2) }", "You can not use placeholders here")

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
            "or(events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), 1, count())",
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
            f"SELECT 1 AS `-- select team_id` FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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
        self.assertEqual(self._select("select 1"), f"SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS}")
        self.assertEqual(self._select("select 1 + 2"), f"SELECT plus(1, 2) LIMIT {MAX_SELECT_RETURNED_ROWS}")
        self.assertEqual(self._select("select 1 + 2, 3"), f"SELECT plus(1, 2), 3 LIMIT {MAX_SELECT_RETURNED_ROWS}")
        self.assertEqual(
            self._select("select 1 + 2, 3 + 4 from events"),
            f"SELECT plus(1, 2), plus(3, 4) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_alias(self):
        # currently not supported!
        self.assertEqual(self._select("select 1 as b"), f"SELECT 1 AS b LIMIT {MAX_SELECT_RETURNED_ROWS}")
        self.assertEqual(
            self._select("select 1 from events as e"),
            f"SELECT 1 FROM events AS e WHERE equals(e.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_from(self):
        self.assertEqual(
            self._select("select 1 from events"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self._assert_select_error("select 1 from other", 'Unknown table "other".')

    def test_select_from_placeholder(self):
        self.assertEqual(
            self._select(
                "select 1 from {placeholder}",
                placeholders={"placeholder": ast.Field(chain=["events"])},
            ),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        with self.assertRaises(QueryError) as error_context:
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
            "A CompareOperation cannot be used as a SELECT source",
        )

    def test_select_cross_join(self):
        self.assertEqual(
            self._select("select 1 from events cross join raw_groups"),
            f"SELECT 1 FROM events CROSS JOIN groups WHERE and(equals(groups.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1 from events, raw_groups"),
            f"SELECT 1 FROM events CROSS JOIN groups WHERE and(equals(groups.team_id, {self.team.pk}), equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_array_join(self):
        self.assertEqual(
            self._select("select 1, a from events array join [1,2,3] as a"),
            f"SELECT 1, a FROM events ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1, a, [1,2,3] as nums from events array join nums as a"),
            f"SELECT 1, a, [1, 2, 3] AS nums FROM events ARRAY JOIN nums AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1, a from events left array join [1,2,3] as a"),
            f"SELECT 1, a FROM events LEFT ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1, a from events inner array join [1,2,3] as a"),
            f"SELECT 1, a FROM events INNER ARRAY JOIN [1, 2, 3] AS a WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_where(self):
        self.assertEqual(
            self._select("select 1 from events where 1 == 2"),
            f"SELECT 1 FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_having(self):
        self.assertEqual(
            self._select("select 1 from events having 1 == 2"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) HAVING 0 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_prewhere(self):
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2 where 2 == 3"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_order_by(self):
        self.assertEqual(
            self._select("select event from events order by event"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event ASC LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select event from events order by event desc"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event DESC LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select event from events order by event desc, timestamp"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) ORDER BY events.event DESC, toTimeZone(events.timestamp, %(hogql_val_0)s) ASC LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_limit(self):
        self.assertEqual(
            self._select("select event from events limit 10"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10",
        )
        self.assertEqual(
            self._select("select event from events limit 1000000"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select event from events limit (select 100000000)"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT min2({MAX_SELECT_RETURNED_ROWS}, (SELECT 100000000))",
        )

        self.assertEqual(
            self._select("select event from events limit (select 100000000) with ties"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT min2({MAX_SELECT_RETURNED_ROWS}, (SELECT 100000000)) WITH TIES",
        )

    def test_select_offset(self):
        # Only the default limit if OFFSET is specified alone
        self.assertEqual(
            self._select("select event from events offset 10"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 10"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 10",
        )
        self.assertEqual(
            self._select("select event from events limit 10 offset 0"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 0",
        )
        self.assertEqual(
            self._select("select event from events limit 10 with ties offset 0"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 WITH TIES OFFSET 0",
        )

    def test_select_limit_by(self):
        self.assertEqual(
            self._select("select event from events limit 10 offset 0 by 1,event"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 OFFSET 0 BY 1, events.event LIMIT 50000",
        )

    def test_select_group_by(self):
        self.assertEqual(
            self._select("select event from events group by event, timestamp"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_distinct(self):
        self.assertEqual(
            self._select("select distinct event from events group by event, timestamp"),
            f"SELECT DISTINCT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_subquery(self):
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp)"),
            f"SELECT event AS event FROM (SELECT DISTINCT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s)) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("SELECT event from (select distinct event from events group by event, timestamp) e"),
            f"SELECT e.event AS event FROM (SELECT DISTINCT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) GROUP BY events.event, toTimeZone(events.timestamp, %(hogql_val_0)s)) AS e LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_union_all(self):
        self.assertEqual(
            self._select("SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select(
                "SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2 UNION ALL SELECT events.event FROM events WHERE 1 = 2"
            ),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE and(equals(events.team_id, {self.team.pk}), 0) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL (SELECT 1 UNION ALL SELECT 1) UNION ALL SELECT 1"),
            f"SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL (SELECT 1 UNION ALL SELECT 1) UNION ALL SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 1"),
            f"SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT 1 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1)"),
            f"SELECT 1 FROM (SELECT 1 UNION ALL SELECT 1) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_sample(self):
        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 1"),
            f"SELECT events.event AS event FROM events SAMPLE 1 WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 0.1 OFFSET 1/10"),
            f"SELECT events.event AS event FROM events SAMPLE 0.1 OFFSET 1/10 WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        self.assertEqual(
            self._select("SELECT events.event FROM events SAMPLE 2/78 OFFSET 999"),
            f"SELECT events.event AS event FROM events SAMPLE 2/78 OFFSET 999 WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
            )
            query = self._select(
                "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id",
                context,
            )
            self.assertEqual(
                query,
                f"SELECT events.event AS event FROM events SAMPLE 2/78 OFFSET 999 LEFT OUTER JOIN (SELECT "
                "argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id, "
                "person_distinct_id_overrides.distinct_id AS distinct_id FROM person_distinct_id_overrides WHERE "
                f"equals(person_distinct_id_overrides.team_id, {self.team.pk}) GROUP BY person_distinct_id_overrides.distinct_id "
                "HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0) "
                "SETTINGS optimize_aggregation_in_order=1) AS events__override ON equals(events.distinct_id, events__override.distinct_id) "
                f"JOIN (SELECT person.id AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), "
                "in(tuple(person.id, person.version), (SELECT person.id AS id, max(person.version) AS version "
                f"FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                "HAVING and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), "
                "ifNull(less(argMax(toTimeZone(person.created_at, %(hogql_val_0)s), person.version), "
                "plus(now64(6, %(hogql_val_1)s), toIntervalDay(1))), 0))))) "
                "SETTINGS optimize_aggregation_in_order=1) AS persons ON equals(persons.id, if(not(empty(events__override.distinct_id)), "
                f"events__override.person_id, events.person_id)) WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
            )
            self.assertEqual(
                self._select(
                    "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id",
                    context,
                ),
                f"SELECT events.event AS event FROM events SAMPLE 2/78 OFFSET 999 LEFT OUTER JOIN (SELECT "
                "argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id, "
                "person_distinct_id_overrides.distinct_id AS distinct_id FROM person_distinct_id_overrides WHERE "
                f"equals(person_distinct_id_overrides.team_id, {self.team.pk}) GROUP BY person_distinct_id_overrides.distinct_id "
                "HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0) "
                "SETTINGS optimize_aggregation_in_order=1) AS events__override ON equals(events.distinct_id, events__override.distinct_id) "
                f"JOIN (SELECT person.id AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), "
                "in(tuple(person.id, person.version), (SELECT person.id AS id, max(person.version) AS version "
                f"FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                "HAVING and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), "
                "ifNull(less(argMax(toTimeZone(person.created_at, %(hogql_val_0)s), person.version), "
                "plus(now64(6, %(hogql_val_1)s), toIntervalDay(1))), 0))))) "
                "SETTINGS optimize_aggregation_in_order=1) AS persons SAMPLE 0.1 ON equals(persons.id, if(not(empty(events__override.distinct_id)), "
                f"events__override.person_id, events.person_id)) WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False):
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
            )
            expected = self._select(
                "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons ON persons.id=events.person_id",
                context,
            )
            self.assertEqual(
                expected,
                f"SELECT events.event AS event FROM events SAMPLE 2/78 OFFSET 999 JOIN (SELECT person.id AS id FROM person WHERE "
                f"and(equals(person.team_id, {self.team.pk}), in(tuple(person.id, person.version), (SELECT person.id AS id, "
                f"max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), ifNull(less(argMax(toTimeZone(person.created_at, "
                f"%(hogql_val_0)s), person.version), plus(now64(6, %(hogql_val_1)s), toIntervalDay(1))), 0))))) SETTINGS optimize_aggregation_in_order=1) "
                f"AS persons ON equals(persons.id, events.person_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
            )
            expected = self._select(
                "SELECT events.event FROM events SAMPLE 2/78 OFFSET 999 JOIN persons SAMPLE 0.1 ON persons.id=events.person_id",
                context,
            )
            self.assertEqual(
                expected,
                f"SELECT events.event AS event FROM events SAMPLE 2/78 OFFSET 999 JOIN (SELECT person.id AS id FROM person WHERE "
                f"and(equals(person.team_id, {self.team.pk}), in(tuple(person.id, person.version), (SELECT person.id AS id, "
                f"max(person.version) AS version FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), ifNull(less(argMax(toTimeZone(person.created_at, "
                f"%(hogql_val_0)s), person.version), plus(now64(6, %(hogql_val_1)s), toIntervalDay(1))), 0))))) SETTINGS optimize_aggregation_in_order=1) "
                f"AS persons SAMPLE 0.1 ON equals(persons.id, events.person_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

    def test_count_distinct(self):
        self.assertEqual(
            self._select("SELECT count(distinct event) as count FROM events"),
            f"SELECT count(DISTINCT events.event) AS count FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_count_star(self):
        self.assertEqual(
            self._select("SELECT count(*) as count FROM events"),
            f"SELECT count(*) AS count FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_count_if_distinct(self):
        self.assertEqual(
            self._select("SELECT countIf(distinct event, event like '%a%') as count FROM events"),
            f"SELECT countIf(DISTINCT events.event, like(events.event, %(hogql_val_0)s)) AS count FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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
                "SELECT now() as a, toDateTime(timestamp) as b, toDate(test_date) as c, toDateTime('2020-02-02') as d, toDateTime('2020-02-02 12:25') as e FROM events",
                context,
            ),
            f"SELECT now64(6, %(hogql_val_0)s) AS a, toDateTime(toTimeZone(events.timestamp, %(hogql_val_1)s), %(hogql_val_2)s) AS b, toDate(events.test_date) AS c, toDateTime(%(hogql_val_3)s, %(hogql_val_4)s) AS d, parseDateTime64BestEffort(%(hogql_val_5)s, 6, %(hogql_val_6)s) AS e FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            context.values,
            {
                "hogql_val_0": "UTC",
                "hogql_val_1": "UTC",
                "hogql_val_2": "UTC",
                "hogql_val_3": "2020-02-02",
                "hogql_val_4": "UTC",
                "hogql_val_5": "2020-02-02 12:25",
                "hogql_val_6": "UTC",
            },
        )

    def test_print_timezone_custom(self):
        self.team.timezone = "Europe/Brussels"
        self.team.save()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        self.assertEqual(
            self._select(
                "SELECT now() as a, toDateTime(timestamp) as b, toDateTime('2020-02-02') as c FROM events",
                context,
            ),
            f"SELECT now64(6, %(hogql_val_0)s) AS a, toDateTime(toTimeZone(events.timestamp, %(hogql_val_1)s), %(hogql_val_2)s) AS b, toDateTime(%(hogql_val_3)s, %(hogql_val_4)s) AS c FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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
        with self.assertRaises(ValueError) as error_context:
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
            f"SELECT events.distinct_id AS distinct_id, min(toTimeZone(events.timestamp, %(hogql_val_0)s)) OVER win1 AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_postgres_compatible_lag_and_lead_functions(self):
        # Simple example without ROWS
        self.assertEqual(
            self._select("SELECT distinct_id, lag(timestamp) OVER (ORDER BY timestamp) FROM events"),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )
        self.assertEqual(
            self._select("SELECT distinct_id, lead(timestamp) OVER (ORDER BY timestamp) FROM events"),
            f"SELECT events.distinct_id AS distinct_id, leadInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )
        # Example with ROWS specified
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lag(timestamp) OVER (ORDER BY timestamp ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM events"
            ),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lead(timestamp) OVER (ORDER BY timestamp ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM events"
            ),
            f"SELECT events.distinct_id AS distinct_id, leadInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )
        # Example with named windows
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lag(timestamp) over win1 as prev_ts FROM events WINDOW win1 as (PARTITION by distinct_id ORDER BY timestamp)"
            ),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_ts FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_2)s) ASC) LIMIT 50000",
        )
        # Example with multiple named windows, to make sure we don't add ROWS BETWEEN for non lag/lead functions
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lag(timestamp) over win1 as prev_ts, min(timestamp) over win1 as min_ts FROM events WINDOW win1 as (PARTITION by distinct_id ORDER BY timestamp)"
            ),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_ts, min(toTimeZone(events.timestamp, %(hogql_val_2)s)) OVER win1 AS min_ts FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_3)s) ASC) LIMIT 50000",
        )
        # Simple example with partiton by
        # Simple example with partition by
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lag(timestamp) OVER (PARTITION BY distinct_id ORDER BY timestamp) FROM events"
            ),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(toTimeZone(events.timestamp, %(hogql_val_0)s))) OVER (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_1)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )

        # No rows but order by exists
        self.assertEqual(
            self._select(
                "SELECT distinct_id, lag(event) OVER (PARTITION BY distinct_id ORDER BY timestamp) FROM events"
            ),
            f"SELECT events.distinct_id AS distinct_id, lagInFrame(toNullable(events.event)) OVER (PARTITION BY events.distinct_id ORDER BY toTimeZone(events.timestamp, %(hogql_val_0)s) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )

    def test_window_functions_with_window(self):
        self.assertEqual(
            self._select(
                "SELECT distinct_id, min(timestamp) over win1 as timestamp FROM events WINDOW win1 as (PARTITION by distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            ),
            f"SELECT events.distinct_id AS distinct_id, min(toTimeZone(events.timestamp, %(hogql_val_0)s)) OVER win1 AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk}) WINDOW win1 AS (PARTITION BY events.distinct_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_window_functions_with_arg(self):
        self.assertEqual(
            self._select(
                "SELECT quantiles(0.0, 0.25, 0.5, 0.75, 1.0)(distinct distinct_id) over () as values FROM events"
            ),
            f"SELECT quantiles(0.0, 0.25, 0.5, 0.75, 1.0)(events.distinct_id) OVER () AS values FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
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
        sunday_week_context = HogQLContext(team_id=self.team.pk, database=Database(None, WeekStartDay.SUNDAY))
        monday_week_context = HogQLContext(team_id=self.team.pk, database=Database(None, WeekStartDay.MONDAY))

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
            self._expr("tumble(toDateTime('2023-06-12'), toIntervalDay('1')) as t"),
            f"tumble(assumeNotNull(toDateTime(toDateTime(%(hogql_val_0)s, %(hogql_val_1)s))), toIntervalDay(%(hogql_val_2)s)) AS t",
        )
        self.assertEqual(
            self._expr("tumble(now(), toIntervalDay('1')) as t"),
            f"tumble(toDateTime(now64(6, %(hogql_val_0)s), 'UTC'), toIntervalDay(%(hogql_val_1)s)) AS t",
        )
        self.assertEqual(
            self._expr("tumble(parseDateTime('2021-01-04+23:00:00', '%Y-%m-%d+%H:%i:%s'), toIntervalDay('1')) as t"),
            f"tumble(assumeNotNull(toDateTime(parseDateTimeOrNull(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s))), toIntervalDay(%(hogql_val_3)s)) AS t",
        )
        self.assertEqual(
            self._expr("tumble(parseDateTimeBestEffort('23/10/2020 12:12:57'), toIntervalDay('1')) as t"),
            f"tumble(assumeNotNull(toDateTime(parseDateTime64BestEffort(%(hogql_val_0)s, 6, %(hogql_val_1)s))), toIntervalDay(%(hogql_val_2)s)) AS t",
        )
        self.assertEqual(
            self._select("SELECT tumble(timestamp, toIntervalDay('1')) as t FROM events"),
            f"SELECT tumble(toDateTime(toTimeZone(events.timestamp, %(hogql_val_0)s), 'UTC'), toIntervalDay(%(hogql_val_1)s)) AS t FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_field_nullable_equals(self):
        generated_sql_statements1 = self._select(
            "SELECT "
            "start_time = toStartOfMonth(now()) as a, "
            "1 = 1 as b, "
            "click_count = 1 as c, "
            "1 = click_count as d, "
            "click_count = keypress_count as e, "
            "click_count = null as f, "
            "null = click_count as g "
            "FROM session_replay_events"
        )
        generated_sql_statements2 = self._select(
            "SELECT "
            "equals(start_time, toStartOfMonth(now())) as a, "
            "equals(1, 1) as b, "
            "equals(click_count, 1) as c, "
            "equals(1, click_count) as d, "
            "equals(click_count, keypress_count) as e, "
            "equals(click_count, null) as f, "
            "equals(null, click_count) as g "
            "FROM session_replay_events"
        )
        assert generated_sql_statements1 == generated_sql_statements2
        assert generated_sql_statements1 == (
            f"SELECT "
            # start_time = toStartOfMonth(now())
            # (the return of toStartOfMonth() is treated as "potentially nullable" since we yet have full typing support)
            f"ifNull(equals(session_replay_events.start_time, toStartOfMonth(now64(6, %(hogql_val_1)s))), "
            f"isNull(session_replay_events.start_time) and isNull(toStartOfMonth(now64(6, %(hogql_val_1)s)))) AS a, "
            # 1 = 1
            f"1 AS b, "
            # click_count = 1
            f"ifNull(equals(session_replay_events.click_count, 1), 0) AS c, "
            # 1 = click_count
            f"ifNull(equals(1, session_replay_events.click_count), 0) AS d, "
            # click_count = keypress_count
            f"ifNull(equals(session_replay_events.click_count, session_replay_events.keypress_count), isNull(session_replay_events.click_count) and isNull(session_replay_events.keypress_count)) AS e, "
            # click_count = null
            f"isNull(session_replay_events.click_count) AS f, "
            # null = click_count
            f"isNull(session_replay_events.click_count) AS g "
            # ...
            f"FROM (SELECT min(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s)) AS start_time, sum(session_replay_events.click_count) AS click_count, sum(session_replay_events.keypress_count) AS keypress_count FROM session_replay_events WHERE equals(session_replay_events.team_id, {self.team.pk})) AS session_replay_events LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_field_nullable_not_equals(self):
        generated_sql1 = self._select(
            "SELECT start_time != toStartOfMonth(now()) as a, 1 != 1 as b, "
            "click_count != 1 as c, 1 != click_count as d, click_count != keypress_count as e, click_count != null as f, null != click_count as g "
            "FROM session_replay_events"
        )
        generated_sql2 = self._select(
            "SELECT notEquals(start_time, toStartOfMonth(now())) as a, notEquals(1, 1) as b, "
            "notEquals(click_count, 1) as c, notEquals(1, click_count) as d, notEquals(click_count, keypress_count) as e, notEquals(click_count, null) as f, notEquals(null, click_count) as g "
            "FROM session_replay_events"
        )
        assert generated_sql1 == generated_sql2
        assert generated_sql1 == (
            f"SELECT "
            # start_time = toStartOfMonth(now())
            # (the return of toStartOfMonth() is treated as "potentially nullable" since we yet have full typing support)
            f"ifNull(notEquals(session_replay_events.start_time, toStartOfMonth(now64(6, %(hogql_val_1)s))), "
            f"isNotNull(session_replay_events.start_time) or isNotNull(toStartOfMonth(now64(6, %(hogql_val_1)s)))) AS a, "
            # 1 = 1
            f"0 AS b, "
            # click_count = 1
            f"ifNull(notEquals(session_replay_events.click_count, 1), 1) AS c, "
            # 1 = click_count
            f"ifNull(notEquals(1, session_replay_events.click_count), 1) AS d, "
            # click_count = keypress_count
            f"ifNull(notEquals(session_replay_events.click_count, session_replay_events.keypress_count), isNotNull(session_replay_events.click_count) or isNotNull(session_replay_events.keypress_count)) AS e, "
            # click_count = null
            f"isNotNull(session_replay_events.click_count) AS f, "
            # null = click_count
            f"isNotNull(session_replay_events.click_count) AS g "
            # ...
            f"FROM (SELECT min(toTimeZone(session_replay_events.min_first_timestamp, %(hogql_val_0)s)) AS start_time, sum(session_replay_events.click_count) AS click_count, sum(session_replay_events.keypress_count) AS keypress_count FROM session_replay_events WHERE equals(session_replay_events.team_id, {self.team.pk})) AS session_replay_events LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_field_nullable_boolean(self):
        PropertyDefinition.objects.create(
            team=self.team, name="is_boolean", property_type="Boolean", type=PropertyDefinition.Type.EVENT
        )
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "is_boolean")
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        generated_sql_statements1 = self._select(
            "SELECT "
            "properties.is_boolean = true,"
            "properties.is_boolean = false, "
            "properties.is_boolean is null "
            "FROM events",
            context=context,
        )
        assert generated_sql_statements1 == (
            f"SELECT "
            "ifNull(equals(toBool(transform(toString(nullIf(nullIf(events.mat_is_boolean, ''), 'null')), %(hogql_val_0)s, %(hogql_val_1)s, NULL)), 1), 0), "
            "ifNull(equals(toBool(transform(toString(nullIf(nullIf(events.mat_is_boolean, ''), 'null')), %(hogql_val_2)s, %(hogql_val_3)s, NULL)), 0), 0), "
            "isNull(toBool(transform(toString(nullIf(nullIf(events.mat_is_boolean, ''), 'null')), %(hogql_val_4)s, %(hogql_val_5)s, NULL))) "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )
        assert context.values == {
            "hogql_val_0": ["true", "false"],
            "hogql_val_1": [1, 0],
            "hogql_val_2": ["true", "false"],
            "hogql_val_3": [1, 0],
            "hogql_val_4": ["true", "false"],
            "hogql_val_5": [1, 0],
        }

    @patch("posthog.hogql.printer.get_materialized_column_for_property")
    def test_ai_trace_id_optimizations(self, mock_get_mat_col):
        """Test that $ai_trace_id gets special treatment for bloom filter index optimization"""

        from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

        mock_mat_col = MaterializedColumn(
            name="mat_$ai_trace_id",
            details=MaterializedColumnDetails(
                table_column="properties", property_name="$ai_trace_id", is_disabled=False
            ),
            is_nullable=True,
        )

        # Basic equality comparison - no ifNull wrapping
        mock_get_mat_col.return_value = mock_mat_col
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        sql = self._select("SELECT * FROM events WHERE properties.$ai_trace_id = 'trace123'", context)

        # Should generate: equals(mat_$ai_trace_id, 'trace123') without ifNull wrapper
        # Check that the WHERE clause contains the direct equals check for $ai_trace_id
        self.assertIn("equals(events.`mat_$ai_trace_id`, %(hogql_val_4)s)", sql)
        # Verify the equals for $ai_trace_id is NOT wrapped in ifNull (it appears directly in WHERE clause)
        self.assertIn("WHERE and(equals(events.team_id,", sql)
        self.assertIn("equals(events.`mat_$ai_trace_id`, %(hogql_val_4)s))", sql)

        # Verify the placeholder value (it's hogql_val_4 due to other parameters in the query)
        self.assertEqual(context.values["hogql_val_4"], "trace123")

        # With materialized column - no nullIf wrapping
        context = HogQLContext(team_id=self.team.pk)
        sql = self._expr("properties.$ai_trace_id", context)

        # Should be: events.mat_$ai_trace_id
        # NOT: nullIf(nullIf(events.mat_$ai_trace_id, ''), 'null')
        self.assertEqual(sql.strip(), "events.`mat_$ai_trace_id`")
        self.assertNotIn("nullIf", sql)

        # IN operations - no ifNull wrapping
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql = self._select("SELECT * FROM events WHERE properties.$ai_trace_id IN ('trace1', 'trace2')", context)

        # Should generate clean IN without ifNull wrapper
        self.assertIn("in(events.`mat_$ai_trace_id`, tuple(%(hogql_val_4)s, %(hogql_val_5)s))", sql)
        self.assertNotIn("ifNull(in", sql)

        # Verify the placeholder values
        self.assertEqual(context.values["hogql_val_4"], "trace1")
        self.assertEqual(context.values["hogql_val_5"], "trace2")

        # Verify other properties still get normal treatment
        mock_get_mat_col.return_value = None  # No materialized column for other props
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        sql = self._select("SELECT * FROM events WHERE properties.other_prop = 'value'", context)

        # Other properties should still have null handling with ifNull wrapping
        self.assertIn(
            "ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_7)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_8)s), 0)",
            sql,
        )

    def test_field_nullable_like(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=Database())
        context.database.events.fields["nullable_field"] = StringDatabaseField(name="nullable_field", nullable=True)  # type: ignore
        generated_sql_statements1 = self._select(
            "SELECT "
            "nullable_field like 'a' as a, "
            "nullable_field like null as b, "
            "null like nullable_field as c, "
            "null like 'a' as d, "
            "'a' like nullable_field as e, "
            "'a' like null as f "
            "FROM events",
            context,
        )

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=Database())
        context.database.events.fields["nullable_field"] = StringDatabaseField(name="nullable_field", nullable=True)  # type: ignore
        generated_sql_statements2 = self._select(
            "SELECT "
            "like(nullable_field, 'a') as a, "
            "like(nullable_field, null) as b, "
            "like(null, nullable_field) as c, "
            "like(null, 'a') as d, "
            "like('a', nullable_field) as e, "
            "like('a', null) as f "
            "FROM events",
            context,
        )
        assert generated_sql_statements1 == generated_sql_statements2
        assert generated_sql_statements1 == (
            f"SELECT "
            # event like 'a',
            "ifNull(like(events.nullable_field, %(hogql_val_0)s), 0) AS a, "
            # event like null,
            "isNull(events.nullable_field) AS b, "
            # null like event,
            "isNull(events.nullable_field) AS c, "
            # null like 'a',
            "ifNull(like(NULL, %(hogql_val_1)s), 0) AS d, "
            # 'a' like event,
            "ifNull(like(%(hogql_val_2)s, events.nullable_field), 0) AS e, "
            # 'a' like null
            "isNull(%(hogql_val_3)s) AS f "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_field_nullable_not_like(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=Database())
        context.database.events.fields["nullable_field"] = StringDatabaseField(name="nullable_field", nullable=True)  # type: ignore
        generated_sql_statements1 = self._select(
            "SELECT "
            "nullable_field not like 'a' as a, "
            "nullable_field not like null as b, "
            "null not like nullable_field as c, "
            "null not like 'a' as d, "
            "'a' not like nullable_field as e, "
            "'a' not like null as f "
            "FROM events",
            context,
        )

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=Database())
        context.database.events.fields["nullable_field"] = StringDatabaseField(name="nullable_field", nullable=True)  # type: ignore
        generated_sql_statements2 = self._select(
            "SELECT "
            "notLike(nullable_field, 'a') as a, "
            "notLike(nullable_field, null) as b, "
            "notLike(null, nullable_field) as c, "
            "notLike(null, 'a') as d, "
            "notLike('a', nullable_field) as e, "
            "notLike('a', null) as f "
            "FROM events",
            context,
        )
        assert generated_sql_statements1 == generated_sql_statements2
        assert generated_sql_statements1 == (
            f"SELECT "
            # event like 'a',
            "ifNull(notLike(events.nullable_field, %(hogql_val_0)s), 1) AS a, "
            # event like null,
            "isNotNull(events.nullable_field) AS b, "
            # null like event,
            "isNotNull(events.nullable_field) AS c, "
            # null like 'a',
            "ifNull(notLike(NULL, %(hogql_val_1)s), 1) AS d, "
            # 'a' like event,
            "ifNull(notLike(%(hogql_val_2)s, events.nullable_field), 1) AS e, "
            # 'a' like null
            "isNotNull(%(hogql_val_3)s) AS f "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}"
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
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_print_query_level_settings(self):
        query = parse_select("SELECT 1 FROM events")
        assert isinstance(query, ast.SelectQuery)
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS optimize_aggregation_in_order=1",
        )

    def test_print_both_settings(self):
        query = parse_select("SELECT 1 FROM events")
        assert isinstance(query, ast.SelectQuery)
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS optimize_aggregation_in_order=1, readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_pretty_print(self):
        printed = self._pretty("SELECT 1, event FROM events")
        self.assertEqual(
            printed,
            f"SELECT\n    1,\n    event\nFROM\n    events\nLIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_pretty_print_subquery(self):
        printed = self._pretty("SELECT 1, event FROM (select 1, event from events)")
        self.assertEqual(
            printed,
            f"""SELECT\n    1,\n    event\nFROM\n    (SELECT\n        1,\n        event\n    FROM\n        events)\nLIMIT {MAX_SELECT_RETURNED_ROWS}""",
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_large_pretty_print(self):
        printed = self._pretty(
            f"""
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
            LIMIT {MAX_SELECT_RETURNED_ROWS}
        """
        )
        assert printed == self.snapshot  # type: ignore

    def test_print_hidden_aliases_timestamp(self):
        query = parse_select("select * from (SELECT timestamp, timestamp FROM events)")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT timestamp AS timestamp FROM (SELECT toTimeZone(events.timestamp, %(hogql_val_0)s), "
            f"toTimeZone(events.timestamp, %(hogql_val_1)s) AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk})) "
            f"LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_print_hidden_aliases_column_override(self):
        query = parse_select("select * from (SELECT timestamp as event, event FROM events)")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT event AS event FROM (SELECT toTimeZone(events.timestamp, %(hogql_val_0)s) AS event, "
            f"event FROM events WHERE equals(events.team_id, {self.team.pk})) "
            f"LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_print_hidden_aliases_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")

        query = parse_select("select * from (SELECT properties.$browser FROM events)")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT `$browser` AS `$browser` FROM (SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` "
            f"FROM events WHERE equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS} "
            f"SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_print_hidden_aliases_double_property(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")

        query = parse_select("select * from (SELECT properties.$browser, properties.$browser FROM events)")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT `$browser` AS `$browser` FROM (SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null'), "
            f"nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` "  # only the second one gets the alias
            f"FROM events WHERE equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS} "
            f"SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )

    def test_lookup_domain_type(self):
        query = parse_select("select hogql_lookupDomainType('www.google.com') as domain from events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'domain_type', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')), "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'domain_type', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS domain "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "format_csv_allow_double_quotes=0, max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        ) == printed

    def test_lookup_paid_source_type(self):
        query = parse_select("select hogql_lookupPaidSourceType('google') as source from events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')) , "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS source "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "format_csv_allow_double_quotes=0, max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        ) == printed

    def test_lookup_paid_medium_type(self):
        query = parse_select("select hogql_lookupPaidMediumType('social') as medium from events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(coalesce(%(hogql_val_0)s, ''), 'medium')) AS medium "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        ) == printed

    def test_lookup_organic_source_type(self):
        query = parse_select("select hogql_lookupOrganicSourceType('google') as source  from events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')), "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS source "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "format_csv_allow_double_quotes=0, max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        ) == printed

    def test_lookup_organic_medium_type(self):
        query = parse_select("select hogql_lookupOrganicMediumType('social') as medium from events")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(coalesce(%(hogql_val_0)s, ''), 'medium')) AS medium "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        ) == printed

    def test_currency_conversion(self):
        query = parse_select("select convertCurrency('USD', 'EUR', 100, toDate('2021-01-01')) as currency")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            (
                f"SELECT if(equals(%(hogql_val_0)s, %(hogql_val_1)s), toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10)) = 0, toDecimal64(0, 10), multiplyDecimal(divideDecimal(toDecimal64(100, 10), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10))), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_1)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10))))) AS currency "
                "LIMIT 50000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
            ),
            printed,
        )

    def test_currency_conversion_without_date(self):
        query = parse_select("select convertCurrency('USD', 'EUR', 100) as currency")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            (
                f"SELECT if(equals(%(hogql_val_0)s, %(hogql_val_1)s), toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, today(), toDecimal64(0, 10)) = 0, toDecimal64(0, 10), multiplyDecimal(divideDecimal(toDecimal64(100, 10), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, today(), toDecimal64(0, 10))), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_1)s, today(), toDecimal64(0, 10))))) AS currency "
                "LIMIT 50000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
            ),
            printed,
        )

    def test_get_survey_response(self):
        # Test with just question index
        with patch("posthog.hogql.printer.get_survey_response_clickhouse_query") as mock_get_survey_response:
            mock_get_survey_response.return_value = "MOCKED SQL FOR SURVEY RESPONSE"

            query = parse_select("select getSurveyResponse(0) from events")
            printed = print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
                settings=HogQLGlobalSettings(max_execution_time=10),
            )

            # Verify the utility function was called with correct parameters
            mock_get_survey_response.assert_called_once_with(0, None, False)

            # Just test that the mock value was inserted into the query
            self.assertIn("MOCKED SQL FOR SURVEY RESPONSE", printed)

        # Test with question index and specific ID
        with patch("posthog.hogql.printer.get_survey_response_clickhouse_query") as mock_get_survey_response:
            mock_get_survey_response.return_value = "MOCKED SQL FOR SURVEY RESPONSE WITH ID"

            query = parse_select("select getSurveyResponse(1, 'question123') from events")
            printed = print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
                settings=HogQLGlobalSettings(max_execution_time=10),
            )

            # Verify the utility function was called with correct parameters
            mock_get_survey_response.assert_called_once_with(1, "question123", False)

            # Just test that the mock value was inserted into the query
            self.assertIn("MOCKED SQL FOR SURVEY RESPONSE WITH ID", printed)

        # Test with multiple choice question
        with patch("posthog.hogql.printer.get_survey_response_clickhouse_query") as mock_get_survey_response:
            mock_get_survey_response.return_value = "MOCKED SQL FOR MULTIPLE CHOICE SURVEY RESPONSE"

            query = parse_select("select getSurveyResponse(2, 'abc123', true) from events")
            printed = print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
                settings=HogQLGlobalSettings(max_execution_time=10),
            )

            # Verify the utility function was called with correct parameters
            mock_get_survey_response.assert_called_once_with(2, "abc123", True)

    def test_unique_survey_submissions_filter(self):
        with patch(
            "posthog.hogql.printer.filter_survey_sent_events_by_unique_submission"
        ) as mock_filter_survey_sent_events_by_unique_submission:
            mock_filter_survey_sent_events_by_unique_submission.return_value = (
                "MOCKED SQL FOR UNIQUE SURVEY SUBMISSIONS FILTER"
            )
            query = parse_select("select uuid from events where uniqueSurveySubmissionsFilter('survey123')")
            printed = print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
                settings=HogQLGlobalSettings(max_execution_time=10),
            )
            mock_filter_survey_sent_events_by_unique_submission.assert_called_once_with("survey123")
            self.assertIn("MOCKED SQL FOR UNIQUE SURVEY SUBMISSIONS FILTER", printed)

    def test_override_timezone(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=Database(None, WeekStartDay.SUNDAY),
        )
        context.database.events.fields["test_date"] = DateDatabaseField(name="test_date")  # type: ignore

        self.assertEqual(
            self._select(
                """
                    SELECT
                        toDateTime(timestamp) as ts,
                        toDateTime(timestamp, 'US/Pacific') as tsz,
                        now() as now,
                        now('US/Pacific') as nowz
                    FROM events
                """,
                context,
            ),
            f"SELECT toDateTime(toTimeZone(events.timestamp, %(hogql_val_0)s), %(hogql_val_1)s) AS ts, toDateTime(toTimeZone(events.timestamp, %(hogql_val_2)s), %(hogql_val_3)s) AS tsz, now64(6, %(hogql_val_4)s) AS now, now64(6, %(hogql_val_5)s) AS nowz FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            context.values,
            {
                "hogql_val_0": "UTC",
                "hogql_val_1": "UTC",
                "hogql_val_2": "UTC",
                "hogql_val_3": "US/Pacific",
                "hogql_val_4": "UTC",
                "hogql_val_5": "US/Pacific",
            },
        )

    def test_trim_leading_trailing_both(self):
        query = parse_select(
            "select trim(LEADING 'xy' FROM 'media') as a, trim(TRAILING 'xy' FROM 'media') as b, trim(BOTH 'xy' FROM 'media') as c"
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert printed == (
            f"SELECT trim(LEADING %(hogql_val_1)s FROM %(hogql_val_0)s) AS a, trim(TRAILING %(hogql_val_3)s FROM %(hogql_val_2)s) AS b, trim(BOTH %(hogql_val_5)s FROM %(hogql_val_4)s) AS c LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1"
        )
        query2 = parse_select(
            "select trimLeft('media', 'xy') as a, trimRight('media', 'xy') as b, trim('media', 'xy') as c"
        )
        printed2 = print_ast(
            query2,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert printed2 == printed

    def test_case_insensitive_functions(self):
        context = HogQLContext(team_id=self.team.pk)
        self.assertEqual(
            self._expr("CoALESce(1)", context),
            "coalesce(1)",
        )
        self.assertEqual(
            self._expr("SuM(1)", context),
            "sum(1)",
        )

    def test_inline_persons(self):
        query = parse_select(
            "select persons.id as person_id from events join persons on persons.id = events.person_id and persons.id in (1,2,3)"
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed

    def test_dont_inline_persons(self):
        query = parse_select(
            "select persons.id as person_id from events join persons on persons.id = events.person_id and persons.id = 1"
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE equals(person.team_id, {self.team.pk})" in printed

    def test_inline_persons_alias(self):
        query = parse_select(
            """
            select p1.id as p1_id from events
            join persons as p1 on p1.id = events.person_id and p1.id in (1,2,3)
            """
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed

    def test_two_joins(self):
        query = parse_select(
            """
            select p1.id as p1_id, p2.id as p2_id from events
            join persons as p1 on p1.id = events.person_id and p1.id in (1,2,3)
            join persons as p2 on p2.id = events.person_id and p2.id in (4,5,6)
            """
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(4, 5, 6)))" in printed

    def test_two_clauses(self):
        query = parse_select(
            """
            select p1.id as p1_id, p2.id as p2_id from events
            join persons as p1 on p1.id in (7,8,9) and p1.id = events.person_id and p1.id in (1,2,3)
            join persons as p2 on p2.id = events.person_id and p2.id in (4,5,6)
            """
        )
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(7, 8, 9)), in(id, tuple(1, 2, 3)))"
            in printed
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(4, 5, 6)))" in printed

    def test_print_hogql_aggregation_function_uses_hogql_function_names(self):
        query = parse_expr("avgArray([1, 2, 3])")
        printed = print_ast(query, HogQLContext(team_id=self.team.pk), dialect="hogql")
        assert printed == "avgArray([1, 2, 3])"

    def test_print_percentage_call_alias(self):
        select = parse_select("SELECT concat('%', 'word', '%') LIMIT 1")
        printed = print_ast(
            select, HogQLContext(team_id=self.team.pk, enable_select_queries=True), dialect="clickhouse"
        )

        assert (
            printed
            == "SELECT concat(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s) AS `concat('', 'word', '')` LIMIT 1"
        )

    def test_print_hogql_output_format(self):
        query = parse_select("select 1 limit 1")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
            dialect="hogql",
        )
        assert printed == "SELECT 1 LIMIT 1"

    def test_print_clickhouse_output_format(self):
        query = parse_select("select 1 limit 1")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
            dialect="clickhouse",
        )
        assert printed == "SELECT 1 LIMIT 1 FORMAT ArrowStream"

    def test_print_clickhouse_output_format_union(self):
        query = parse_select("select 1 limit 1 union all select 2 limit 1")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
            dialect="clickhouse",
        )
        assert printed == "SELECT 1 LIMIT 1 UNION ALL SELECT 2 LIMIT 1 FORMAT ArrowStream"

    def test_print_clickhouse_output_format_union_with_nested_union_subquery(self):
        query = parse_select("select * from (select 1 as num union all select 2 as num) limit 2")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
            dialect="clickhouse",
        )
        assert (
            printed == "SELECT num AS num FROM (SELECT 1 AS num UNION ALL SELECT 2 AS num) LIMIT 2 FORMAT ArrowStream"
        )

    def test_print_hogql_in_cohort(self):
        Cohort.objects.create(team=self.team, name="some fake cohort", created_by=self.user)
        query = parse_select(
            "select event from events where event = 'purchase' and person_id in cohort 'some fake cohort'"
        )
        printed = print_prepared_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="hogql",
        )
        assert (
            printed
            == "SELECT event FROM events WHERE and(equals(event, 'purchase'), person_id IN COHORT 'some fake cohort') LIMIT 50000"
        )

    def test_print_hogql_not_in_cohort(self):
        Cohort.objects.create(team=self.team, name="some fake cohort", created_by=self.user)
        query = parse_select(
            "select event from events where event = 'purchase' and person_id not in cohort 'some fake cohort'"
        )
        printed = print_prepared_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="hogql",
        )
        assert (
            printed
            == "SELECT event FROM events WHERE and(equals(event, 'purchase'), person_id NOT IN COHORT 'some fake cohort') LIMIT 50000"
        )

    def test_can_call_parametric_function(self):
        query = parse_select("SELECT arrayReduce('sum', [1, 2, 3])")
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
        )
        assert printed == (
            "SELECT arrayReduce(%(hogql_val_0)s, [1, 2, 3]) AS `arrayReduce('sum', [1, 2, 3])` LIMIT 50000"
        )

    def test_can_call_parametric_function_from_placeholder(self):
        query = parse_select("SELECT arrayReduce({f}, [1, 2, 3])", placeholders={"f": ast.Constant(value="sum")})
        printed = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
        )
        assert printed == (
            "SELECT arrayReduce(%(hogql_val_0)s, [1, 2, 3]) AS `arrayReduce('sum', [1, 2, " "3])` LIMIT 50000"
        )

    def test_fails_on_parametric_function_with_no_arguments(self):
        query = parse_select("SELECT arrayReduce()")
        with pytest.raises(QueryError, match="Missing arguments in function 'arrayReduce'"):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_numeric(self):
        query = parse_select("SELECT arrayReduce(1, [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got IntegerType '1'"
        ):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_lambda(self):
        query = parse_select("SELECT arrayReduce(x -> x, [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got Lambda"
        ):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_expression(self):
        query = parse_select("SELECT arrayReduce('ev' + 'il', [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got ArithmeticOperation"
        ):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_missing(self):
        query = parse_select("SELECT arrayReduce('evil', [1, 2, 3])")
        with pytest.raises(QueryError, match="Invalid parametric function in 'arrayReduce', 'evil' is not supported."):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_invalid(self):
        query = parse_select("SELECT arrayReduce('array_agg', [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Invalid parametric function in 'arrayReduce', 'array_agg' is not supported."
        ):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_with_evil_placeholder(self):
        query = parse_select("SELECT arrayReduce({f}, [1, 2, 3])", placeholders={"f": ast.Constant(value="evil")})
        with pytest.raises(QueryError, match="Invalid parametric function in 'arrayReduce', 'evil' is not supported."):
            print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_team_id_guarding_events(self):
        sql = self._select(
            "SELECT event FROM events",
        )
        assert (
            sql == f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000"
        )

    @parameterized.expand([[True], [False]])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_with_cte(self, using_global_joins):
        with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", using_global_joins):
            credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="key", access_secret="secret"
            )
            DataWarehouseTable.objects.create(
                team=self.team,
                name="test_table",
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern="http://s3/folder/",
                credential=credential,
                columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            )
            printed = self._select("""
                WITH some_remote_table AS
                (
                    SELECT * FROM test_table
                )
                SELECT event FROM events
                JOIN some_remote_table ON events.event = toString(some_remote_table.id)""")

            if using_global_joins:
                assert "GLOBAL JOIN" in printed
            else:
                assert "GLOBAL JOIN" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([[True], [False]])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_with_cte_nested(self, using_global_joins):
        with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", using_global_joins):
            credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="key", access_secret="secret"
            )
            DataWarehouseTable.objects.create(
                team=self.team,
                name="test_table",
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern="http://s3/folder/",
                credential=credential,
                columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            )
            printed = self._select("""
                WITH some_remote_table AS
                (
                    SELECT e.event, t.id FROM events e
                    JOIN test_table t on toString(t.id) = e.event
                )
                SELECT some_remote_table.event FROM events
                JOIN some_remote_table ON events.event = toString(some_remote_table.id)""")

            if using_global_joins:
                assert "GLOBAL JOIN" in printed
            else:
                assert "GLOBAL JOIN" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([[True], [False]])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_with_multiple_joins(self, using_global_joins):
        with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", using_global_joins):
            credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="key", access_secret="secret"
            )
            DataWarehouseTable.objects.create(
                team=self.team,
                name="test_table",
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern="http://s3/folder/",
                credential=credential,
                columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            )
            printed = self._select("""
                SELECT e.event, s.event, t.id
                FROM events e
                JOIN (SELECT event from events) as s ON e.event = s.event
                LEFT JOIN test_table t on e.event = toString(t.id)""")

            if using_global_joins:
                assert "GLOBAL JOIN" in printed  # Join #1
                assert "GLOBAL LEFT JOIN" in printed  # Join #2
            else:
                assert "GLOBAL JOIN" not in printed  # Join #1
                assert "GLOBAL LEFT JOIN" not in printed  # Join #2

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([[True], [False]])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_with_in_and_property_type(self, using_global_joins):
        with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", using_global_joins):
            credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="key", access_secret="secret"
            )
            DataWarehouseTable.objects.create(
                team=self.team,
                name="test_table",
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern="http://s3/folder/",
                credential=credential,
                columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            )

            printed = self._select("""
                SELECT event FROM events
                WHERE properties.$browser IN (
                    SELECT id FROM test_table
                )""")

            if using_global_joins:
                assert "globalIn" in printed
            else:
                assert "globalIn" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([[True], [False]])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_anonymous_tables(self, using_global_joins):
        with mock.patch("posthog.hogql.resolver.USE_GLOBAL_JOINS", using_global_joins):
            credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="key", access_secret="secret"
            )
            DataWarehouseTable.objects.create(
                team=self.team,
                name="test_table",
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                url_pattern="http://s3/folder/",
                credential=credential,
                columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            )

            printed = self._select("""
                select e.event, ij.remote_id
                from events e
                inner join (
                    select *
                    from (
                        select p.id as person_id, rt.id as remote_id
                        from persons p
                        left join (
                            select * from test_table
                        ) rt on rt.id = p.id
                    )
                ) as ij on e.event = ij.remote_id""")

            if using_global_joins:
                assert "GLOBAL INNER JOIN" in printed
            else:
                assert "GLOBAL INNER JOIN" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore


class TestPrinted(APIBaseTest):
    def test_can_call_parametric_function(self):
        query = parse_select("SELECT arrayReduce('sum', [1, 2, 3])")
        query_response = execute_hogql_query(
            team=self.team,
            query=query,
        )
        assert query_response.results == [(6,)]
