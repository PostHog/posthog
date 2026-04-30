import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Optional, cast

import pytest
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    clean_varying_query_parts,
    cleanup_materialized_columns,
    flush_persons_and_events,
    get_index_from_explain,
    materialized,
    snapshot_clickhouse_queries,
)
from unittest import mock
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    HogQLQueryModifiers,
    MaterializationMode,
    MaterializedColumnsOptimizationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    PropertyGroupsMode,
    SessionTableVersion,
)

from posthog.hogql import ast
from posthog.hogql.constants import (
    MAX_SELECT_POSTHOG_AI_LIMIT,
    MAX_SELECT_RETURNED_ROWS,
    HogQLDialect,
    HogQLGlobalSettings,
    HogQLParserBackend,
    HogQLQuerySettings,
    LimitContext,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DateDatabaseField, StringDatabaseField
from posthog.hogql.errors import ExposedHogQLError, ImpossibleASTError, QueryError
from posthog.hogql.hogqlx import convert_tag_to_hx
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast, to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import PropertyDefinition
from posthog.models.cohort.cohort import Cohort
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DICTIONARY_NAME
from posthog.models.team.team import WeekStartDay
from posthog.settings.data_stores import CLICKHOUSE_DATABASE

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseTable
from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import (
    get_bloom_filter_index_name,
    get_minmax_index_name,
    get_ngram_lower_index_name,
    materialize,
)


class TestPrinter(BaseTest):
    maxDiff = None

    # Helper to always translate HogQL with a blank context
    def _expr(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        dialect: HogQLDialect = "clickhouse",
        settings: Optional[HogQLQuerySettings] = None,
        backend: HogQLParserBackend = "cpp-json",
    ) -> str:
        node = parse_expr(query, backend=backend)
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(
            select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])), settings=settings
        )
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
        return prepare_and_print_ast(
            parse_select(query, placeholders=placeholders),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )[0]

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

    def _assert_query_error(self, statement, expected_error):
        with self.assertRaises(QueryError) as context:
            self._select(statement, None)
        if expected_error not in str(context.exception):
            raise AssertionError(f"Expected '{expected_error}' in '{str(context.exception)}'")
        self.assertTrue(expected_error in str(context.exception))

    def _pretty(self, query: str):
        printed, _ = prepare_and_print_ast(
            parse_select(query),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "hogql",
            pretty=True,
        )
        return printed

    def _print(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        placeholders: Optional[dict[str, ast.Expr]] = None,
        settings: Optional[HogQLGlobalSettings] = None,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ) -> str:
        parsed = parse_select(query, placeholders=placeholders)
        printed, _ = prepare_and_print_ast(
            parsed,
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect=dialect,
            settings=settings,
        )
        return printed

    def test_to_printed_hogql(self):
        expr = parse_select("select 1 + 2, 3 from events")
        repsponse = to_printed_hogql(expr, self.team)
        self.assertEqual(
            repsponse, f"SELECT\n    plus(1, 2),\n    3\nFROM\n    events\nLIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_column_aliases_select_star_subquery_uses_real_column_names(self):
        printed = self._select("select s.* from (select 1 as x, 2 as y, 3 as z) as s (a, b, c)")
        # ClickHouse doesn't support (a, b, c) syntax, so the printer should
        # bake aliases into the inner SELECT
        self.assertNotIn("(a, b, c)", printed)
        self.assertIn("AS a", printed)
        self.assertIn("AS b", printed)
        self.assertIn("AS c", printed)

    def test_column_aliases_explicit_aliased_refs_use_real_names(self):
        printed = self._select("select e.a, e.b from events as e (a, b, c)")
        # e.a should resolve to e.uuid, e.b to e.event in ClickHouse
        self.assertIn("e.uuid", printed)
        self.assertIn("e.event", printed)
        self.assertNotIn("e.a", printed)
        self.assertNotIn("e.b", printed)

    def test_column_aliases_in_where_clause(self):
        printed = self._select("select e.a from events as e (a, b, c) where e.c is not null")
        self.assertIn("e.uuid", printed)
        self.assertIn("e.properties", printed)
        self.assertNotIn("e.a", printed)
        self.assertNotIn("e.c", printed)

    def test_column_aliases_unqualified_refs(self):
        printed = self._select("select a, b from events as e (a, b, c)")
        self.assertIn("e.uuid", printed)
        self.assertIn("e.event", printed)

    def test_column_aliases_remaining_columns_keep_original_names(self):
        # Only 3 aliases for a table with many columns — remaining keep original names
        printed = self._select("select e.a, e.timestamp from events as e (a, b, c)")
        self.assertIn("e.uuid", printed)
        self.assertIn("toTimeZone(e.timestamp", printed)

    def test_column_aliases_original_name_not_accessible(self):
        self._assert_select_error(
            "select e.uuid from events as e (a, b, c)",
            "Field not found: uuid",
        )

    def test_column_aliases_subquery_bakes_into_inner_select(self):
        printed = self._select("select s.a from (select 1 as x, 2 as y) as s (a, b)")
        # For ClickHouse, column aliases are baked into the inner SELECT
        self.assertIn("AS a", printed)
        self.assertIn("AS b", printed)
        self.assertNotIn("(a, b)", printed)

    def test_column_aliases_too_many_error(self):
        self._assert_query_error(
            "select 1 from (select 1 as x) as s (a, b)",
            "1 column(s) but 2 column name(s) were provided",
        )

    @parameterized.expand(
        [
            ("range", "select range from range(10)", "range() is not supported in ClickHouse dialect"),
            (
                "generate_series",
                "select generate_series from generate_series(1, 10)",
                "generate_series() is not supported in ClickHouse dialect",
            ),
        ]
    )
    def test_table_function_not_supported_in_clickhouse(self, _name, query, expected_error):
        self._assert_select_error(query, expected_error)

    def test_lambda_style_clickhouse_prints(self):
        printed = self._select("select lambda x: x + 1")
        self.assertIn("x -> plus(x, 1)", printed)

    def test_array_slice_clickhouse_prints_array_slice(self):
        printed = self._select("select [1, 2, 3][1:3]")
        self.assertIn("arraySlice([1, 2, 3], 1, plus(minus(3, 1), 1))", printed)

    def test_try_cast_non_postgres_error(self):
        self._assert_query_error(
            "select try_cast(1 as Int64)",
            "TRY_CAST is not allowed in clickhouse dialect",
        )

    def test_limit_percent_clickhouse_constant_prints_decimal(self):
        printed = self._select("select 1 from events limit 40 %")
        self.assertIn("LIMIT 0.4", printed)

    def test_limit_percent_clickhouse_expression_error(self):
        self._assert_query_error(
            "select 1 from events limit (60 + 7) %",
            "LIMIT percent with expressions is not supported in clickhouse dialect",
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

    def test_intersect_all_raises_in_clickhouse(self):
        with self.assertRaises(ImpossibleASTError) as context:
            self._select("select 1 as id intersect all select 2 as id")
        self.assertIn("INTERSECT ALL is not supported", str(context.exception))

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

    def test_except_all_raises_in_clickhouse(self):
        with self.assertRaises(ImpossibleASTError) as context:
            self._select("select 1 as id except all select 2 as id")
        self.assertIn("EXCEPT ALL is not supported", str(context.exception))

    def test_union_by_name(self):
        expr = parse_select("""select 1 as a, 2 as b union by name select 3 as b, 4 as a""")
        response = to_printed_hogql(expr, self.team)
        self.assertEqual(
            response,
            (
                "SELECT\n"
                "    1 AS a,\n"
                "    2 AS b\n"
                "LIMIT 50000\n"
                "UNION DISTINCT BY NAME\n"
                "SELECT\n"
                "    3 AS b,\n"
                "    4 AS a\n"
                f"LIMIT {MAX_SELECT_RETURNED_ROWS}"
            ),
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

    def test_ignore_nulls_prints(self):
        self.assertEqual(
            self._select("SELECT event IGNORE NULLS FROM events"),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000",
        )

    def test_select_set_order_by_prints(self):
        self.assertEqual(
            self._select("select 1 union all select 2 order by 1"),
            "SELECT 1 LIMIT 50000 UNION ALL SELECT 2 ORDER BY 1 ASC LIMIT 50000",
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
        expected_skip_indexes_not_used: set[str] | None = None,
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
            self.assertLessEqual(expected_context_values.items(), context.values.items())

        if expected_skip_indexes_used is not None or expected_skip_indexes_not_used is not None:
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

            # Include HogQLGlobalSettings() so that when we check indexes, we see what skip indexes would be used with realistic settings.
            # E.g. settings like `transform_null_in=1` can make a dramatic difference to the indexes for queries with `in(X, Y)`
            [[raw_explain_result]] = sync_execute(
                f"EXPLAIN indexes = 1, json = 1 SELECT count() FROM events WHERE {printed_expr}",
                context.values,
                settings={
                    k: "1" if v is True else "0" if v is False else str(v)
                    for k, v in HogQLGlobalSettings().model_dump().items()
                    if v is not None
                },
            )
            read_from_merge_tree_step = _find_node(
                json.loads(raw_explain_result)[0]["Plan"],
                condition=lambda node: node["Node Type"] == "ReadFromMergeTree",
            )
            indexes = {
                index["Name"] for index in read_from_merge_tree_step.get("Indexes", []) if index["Type"] == "Skip"
            }
            if expected_skip_indexes_used:
                self.assertTrue(
                    expected_skip_indexes_used.issubset(indexes),
                )
            if expected_skip_indexes_not_used:
                self.assertTrue(
                    expected_skip_indexes_not_used.isdisjoint(indexes),
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
        # We check which skip indexes are used on the test DB, but please test this on a prod-sized DB too when changing this.
        self._test_property_group_comparison(
            "properties.key IN ('a', 'b')",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), in(events.properties_group_custom[%(hogql_val_0)s], tuple(%(hogql_val_1)s, %(hogql_val_2)s)))",
            {"hogql_val_0": "key", "hogql_val_1": "a", "hogql_val_2": "b"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
            expected_skip_indexes_not_used={"properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN ['a', 'b']",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), in(events.properties_group_custom[%(hogql_val_0)s], tuple(%(hogql_val_1)s, %(hogql_val_2)s)))",
            {"hogql_val_0": "key", "hogql_val_1": "a", "hogql_val_2": "b"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
            expected_skip_indexes_not_used={"properties_group_custom_values_bf"},
        )

        # Single string value converts to equality comparison
        self._test_property_group_comparison(
            "properties.key IN 'a'",  # strange, but syntactically valid
            "equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s)",
            {"hogql_val_0": "key", "hogql_val_1": "a"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )
        self._test_property_group_comparison(
            "properties.key IN ['a']",
            "equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s)",
            {"hogql_val_0": "key", "hogql_val_1": "a"},
            expected_skip_indexes_used={"properties_group_custom_keys_bf", "properties_group_custom_values_bf"},
        )

        # Single empty string does need to check if the key exists as well as equality
        self._test_property_group_comparison(
            "properties.key IN ''",
            "and(has(events.properties_group_custom, %(hogql_val_0)s), equals(events.properties_group_custom[%(hogql_val_0)s], %(hogql_val_1)s))",
            {"hogql_val_0": "key", "hogql_val_1": ""},
            expected_skip_indexes_used={"properties_group_custom_keys_bf"},
            expected_skip_indexes_not_used={"properties_group_custom_values_bf"},
        )

        # Tuples with empty string or NULL - bail out of tuple optimization (use default behavior)
        self._test_property_group_comparison("properties.key IN ('a', 'b', '')", None)
        self._test_property_group_comparison("properties.key IN ('', NULL)", None)
        self._test_property_group_comparison("properties.key IN ('a', 'b', NULL)", None)

        # NULL values are can be equal if using transform_null_in = 1, which we do by default
        # https://clickhouse.com/docs/operations/settings/settings#transform_null_in
        # https://clickhouse.com/docs/en/sql-reference/operators/in#null-processing
        self.assertTrue(
            HogQLGlobalSettings().transform_null_in
        )  # if changing this assumption, you'll need to change the printer too
        self._test_property_group_comparison(
            "properties.key in NULL",
            "in(has(events.properties_group_custom, %(hogql_val_2)s) ? events.properties_group_custom[%(hogql_val_2)s] : null, NULL)",
        )
        self._test_property_group_comparison(
            "properties.key in (NULL)",
            "in(has(events.properties_group_custom, %(hogql_val_2)s) ? events.properties_group_custom[%(hogql_val_2)s] : null, NULL)",
        )
        self._test_property_group_comparison(
            "properties.key in (NULL, NULL, NULL)",
            "in(has(events.properties_group_custom, %(hogql_val_2)s) ? events.properties_group_custom[%(hogql_val_2)s] : null, tuple(NULL, NULL, NULL))",
        )
        self._test_property_group_comparison(
            "properties.key in [NULL, NULL, NULL]",
            "in(has(events.properties_group_custom, %(hogql_val_2)s) ? events.properties_group_custom[%(hogql_val_2)s] : null, [NULL, NULL, NULL])",
        )

        # Don't optimize comparisons to types that require additional type conversions.
        self._test_property_group_comparison("properties.key in true", None)
        self._test_property_group_comparison("properties.key in (true, false)", None)
        self._test_property_group_comparison("properties.key in 1", None)
        self._test_property_group_comparison("properties.key in (1, 2, 3)", None)

        # Only direct constant comparison is supported for now -- see above.
        self._test_property_group_comparison("properties.key in lower('value')", None)
        self._test_property_group_comparison("properties.key in (lower('a'), lower('b'))", None)

    def test_event_property_groups_optimized_in_query_results(self):
        _create_event(
            team=self.team,
            distinct_id="distinct_id",
            event="event",
            properties={"label": "string", "value": "s"},
        )
        _create_event(
            team=self.team,
            distinct_id="distinct_id",
            event="event",
            properties={"label": "empty_string", "value": ""},
        )
        _create_event(
            team=self.team,
            distinct_id="distinct_id",
            event="event",
            properties={"label": "null", "value": None},
        )
        _create_event(
            team=self.team,
            distinct_id="distinct_id",
            event="event",
            properties={"label": "not_set"},
        )
        _create_event(
            team=self.team,
            distinct_id="distinct_id",
            event="event",
            properties={"label": "int", "value": 1},
        )

        # update this test if we add more modes
        assert {e.value for e in PropertyGroupsMode} == {
            PropertyGroupsMode.DISABLED,
            PropertyGroupsMode.ENABLED,
            PropertyGroupsMode.OPTIMIZED,
        }

        def assert_result_is_equal(expr: str, labels):
            hogql_expr = parse_expr(expr)

            query = parse_select(
                "select properties.label as label from events where properties.value in {expr} order by label asc",
                placeholders={"expr": hogql_expr},
            )

            disabled_context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    propertyGroupsMode=PropertyGroupsMode.DISABLED,
                ),
            )
            enabled_context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    propertyGroupsMode=PropertyGroupsMode.ENABLED,
                ),
            )
            optimized_context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    propertyGroupsMode=PropertyGroupsMode.OPTIMIZED,
                ),
            )

            disabled_response = execute_hogql_query(
                query=query, team=self.team, context=disabled_context, modifiers=disabled_context.modifiers
            )
            enabled_response = execute_hogql_query(
                query=query, team=self.team, context=enabled_context, modifiers=enabled_context.modifiers
            )
            optimized_response = execute_hogql_query(
                query=query, team=self.team, context=optimized_context, modifiers=optimized_context.modifiers
            )

            assert disabled_response.clickhouse and enabled_response.clickhouse and optimized_response.clickhouse
            assert "properties_group_custom" not in disabled_response.clickhouse
            assert "properties_group_custom" in enabled_response.clickhouse
            assert "properties_group_custom" in optimized_response.clickhouse
            assert {row[0] for row in disabled_response.results} == labels
            assert {row[0] for row in enabled_response.results} == labels
            assert {row[0] for row in optimized_response.results} == labels

        assert_result_is_equal("1", {"int"})
        assert_result_is_equal("'1'", {"int"})  # this feels wrong, but at least it's consistent
        assert_result_is_equal("'s'", {"string"})
        assert_result_is_equal("''", {"empty_string"})
        assert_result_is_equal("NULL", {"null", "not_set"})
        assert_result_is_equal("('s')", {"string"})
        assert_result_is_equal("('s', 's')", {"string"})
        assert_result_is_equal("['s', 's']", {"string"})
        assert_result_is_equal("(NULL)", {"null", "not_set"})
        assert_result_is_equal("(NULL, NULL, NULL)", {"null", "not_set"})
        assert_result_is_equal("[NULL, NULL, NULL]", {"null", "not_set"})
        assert_result_is_equal("('s', 1)", {"string", "int"})
        assert_result_is_equal("('s', '')", {"string", "empty_string"})
        assert_result_is_equal("'null'", set())
        assert_result_is_equal("'NULL'", set())
        assert_result_is_equal("[]", set())

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
        printed, _ = prepare_and_print_ast(parsed, build_context(PropertyGroupsMode.OPTIMIZED), dialect="clickhouse")
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
        assert (
            prepare_and_print_ast(parsed, build_context(PropertyGroupsMode.OPTIMIZED), dialect="clickhouse")[0]
            == prepare_and_print_ast(parsed, build_context(PropertyGroupsMode.ENABLED), dialect="clickhouse")[0]
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

    @parameterized.expand([["percentile_cont"], ["percentile_disc"]])
    def test_percentile_within_group_printer(self, function_name: str):
        self.assertEqual(
            self._expr(f"{function_name}(0.5) within group (order by event desc)", dialect="hogql"),
            f"{function_name}(0.5) WITHIN GROUP (ORDER BY event DESC)",
        )

    @parameterized.expand([["percentile_cont"], ["percentile_disc"]])
    def test_percentile_within_group_parse_errors(self, function_name: str):
        self._assert_expr_error(
            f"{function_name}(0.5)",
            f"Aggregation '{function_name}' requires WITHIN GROUP",
        )
        self._assert_expr_error(
            f"{function_name}(0.5) within group (order by event desc)",
            f"Aggregation '{function_name}' with WITHIN GROUP is not supported in ClickHouse dialect",
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

    def test_boolean_and_optimization(self):
        self.assertEqual(
            self._expr("team_id=1 AND 1 AND event='name'"),
            "and(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s))",
        )
        self.assertEqual(
            self._expr("team_id=1 AND 1"),
            "equals(events.team_id, 1)",
        )
        self.assertEqual(
            self._expr("team_id=1 AND 0"),
            "0",
        )
        self.assertEqual(
            self._expr("team_id=1 AND (1=1 AND event='name')"),
            "and(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s))",
        )
        self.assertEqual(
            self._expr("team_id=1 AND (0=1 AND event='name')"),
            "0",
        )

    def test_boolean_or_optimization(self):
        self.assertEqual(
            self._expr("team_id=1 OR 0 OR event='name'"),
            "or(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s))",
        )
        self.assertEqual(
            self._expr("team_id=1 OR 0"),
            "equals(events.team_id, 1)",
        )
        self.assertEqual(
            self._expr("team_id=1 OR 1"),
            "1",
        )
        self.assertEqual(
            self._expr("team_id=1 OR (1=1 OR event='name')"),
            "1",
        )
        self.assertEqual(
            self._expr("team_id=1 OR (0=1 OR event='name')"),
            "or(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s))",
        )

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
            self._expr("event or timestamp or count()"),
            "or(events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), count())",
        )
        self.assertEqual(
            self._expr("event or timestamp or true or count()"),
            "1",
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

    @parameterized.expand(
        [
            ("sql_injection", "; DROP TABLE events --"),
            ("union_injection", "current_date UNION SELECT 1"),
            ("whitespace", "current date"),
            ("special_chars", "now()"),
            ("empty_string", ""),
        ]
    )
    def test_keyword_rejects_invalid_names(self, _name: str, keyword_name: str):
        node = ast.Keyword(name=keyword_name)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        with self.assertRaises(QueryError):
            print_prepared_ast(node, context=context, dialect="clickhouse", stack=[select_query])

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
        self._assert_query_error("select 1 from other", "Unknown table `other`.")

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

    def test_left_join_team_id_in_on_clause(self):
        # LEFT JOINs should have team_id in ON clause, not WHERE, to preserve LEFT JOIN semantics
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        select_query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    join_type="LEFT JOIN",
                    table=ast.Field(chain=["events"]),
                    alias="e2",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["events", "event"]),
                            right=ast.Field(chain=["e2", "event"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

        prepared = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="clickhouse", stack=[select_query]),
        )
        result = print_prepared_ast(prepared, context=context, dialect="clickhouse", stack=[])

        # The main events table should have its team_id filter in WHERE
        where_start = result.find("WHERE")
        where_clause = result[where_start:] if where_start != -1 else ""
        self.assertIn(f"equals(events.team_id, {self.team.pk})", where_clause)

        # The LEFT JOINed table (alias 'e2') should have team_id in ON clause, NOT in WHERE
        on_start = result.find("ON")
        on_clause = result[on_start:where_start] if on_start != -1 and where_start != -1 else ""
        self.assertIn(f"equals(e2.team_id, {self.team.pk})", on_clause)
        self.assertNotIn("e2.team_id", where_clause)

    def test_inner_join_team_id_in_where_clause(self):
        # INNER JOINs should still have team_id in WHERE clause (current behavior)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        select_query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    join_type="JOIN",
                    table=ast.Field(chain=["events"]),
                    alias="e2",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["events", "event"]),
                            right=ast.Field(chain=["e2", "event"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

        prepared = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="clickhouse", stack=[select_query]),
        )
        result = print_prepared_ast(prepared, context=context, dialect="clickhouse", stack=[])

        # Both tables should have team_id filters in the WHERE clause for INNER JOIN
        where_start = result.find("WHERE")
        where_clause = result[where_start:] if where_start != -1 else ""
        self.assertIn(f"equals(events.team_id, {self.team.pk})", where_clause)
        self.assertIn(f"equals(e2.team_id, {self.team.pk})", where_clause)

    @parameterized.expand(
        [
            ("gte", ast.CompareOperationOp.GtEq, True),
            ("gt", ast.CompareOperationOp.Gt, True),
            ("lte", ast.CompareOperationOp.LtEq, True),
            ("lt", ast.CompareOperationOp.Lt, True),
            ("not_eq", ast.CompareOperationOp.NotEq, True),
            ("eq", ast.CompareOperationOp.Eq, False),
        ],
    )
    def test_join_analyzer_by_comparison_op(self, _name: str, op: ast.CompareOperationOp, expects_analyzer: bool):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        settings = HogQLGlobalSettings()

        select_query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    join_type="LEFT JOIN",
                    table=ast.Field(chain=["events"]),
                    alias="e2",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=op,
                            left=ast.Field(chain=["events", "event"]),
                            right=ast.Field(chain=["e2", "event"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

        prepared = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="clickhouse", stack=[select_query]),
        )
        result = print_prepared_ast(prepared, context=context, dialect="clickhouse", stack=[], settings=settings)

        if expects_analyzer:
            self.assertIn("enable_analyzer=1", result)
        else:
            self.assertNotIn("enable_analyzer=1", result)

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

    def test_select_positional_join(self):
        result = self._select("select 1 from events positional join groups")
        self.assertIn("POSITIONAL JOIN", result)

    def test_select_where(self):
        self.assertEqual(
            self._select("select 1 from events where 1 == 1"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        self.assertEqual(
            self._select("select 1 from events where 1 == 2"),
            f"SELECT 1 FROM events WHERE 0 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_function_filter_prints(self):
        result = self._select("select sum(event) filter (where event = 'a') from events")
        self.assertIn("FILTER (WHERE", result)

    def test_with_clause_before_parens_select_set_prints(self):
        self.assertEqual(
            self._select("WITH cte AS (SELECT 1 AS a) (SELECT a FROM cte UNION ALL SELECT a FROM cte)"),
            "WITH cte AS (SELECT 1 AS a) SELECT cte.a AS a FROM cte LIMIT 50000 UNION ALL SELECT cte.a AS a FROM cte LIMIT 50000",
        )

        self.assertEqual(
            self._select("select 1 from events where event='name'"),
            f"SELECT 1 FROM events WHERE and(equals(events.team_id, {self.team.pk}), equals(events.event, %(hogql_val_0)s)) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_having(self):
        self.assertEqual(
            self._select("select 1 from events having 1 == 2"),
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) HAVING 0 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_select_qualify_not_supported_in_clickhouse(self):
        self._assert_select_error(
            "select row_number() OVER () as rn from events qualify rn = 1",
            "QUALIFY is not supported in the 'clickhouse' dialect",
        )

    def test_select_prewhere(self):
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2 where 2 == 3"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE 0 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select("select 1 from events prewhere 1 == 2 where event='name'"),
            f"SELECT 1 FROM events PREWHERE 0 WHERE and(equals(events.team_id, {self.team.pk}), equals(events.event, %(hogql_val_0)s)) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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

    @parameterized.expand(
        [
            [
                "bare",
                "select event from events order by event WITH FILL",
                "ORDER BY events.event ASC WITH FILL",
            ],
            [
                "from_to_step",
                "select event from events order by event WITH FILL FROM 0 TO 10 STEP 1",
                "ORDER BY events.event ASC WITH FILL FROM 0 TO 10 STEP 1",
            ],
            [
                "desc_from_to",
                "select event from events order by event DESC WITH FILL FROM 0 TO 10",
                "ORDER BY events.event DESC WITH FILL FROM 0 TO 10",
            ],
            [
                "interpolate",
                "select event, distinct_id from events order by event WITH FILL FROM 'a' TO 'z' INTERPOLATE (distinct_id AS 0)",
                "ORDER BY events.event ASC WITH FILL FROM %(hogql_val_0)s TO %(hogql_val_1)s INTERPOLATE (`events.distinct_id` AS 0)",
            ],
            [
                "naked_interpolate",
                "select event from events order by event WITH FILL FROM 0 TO 10 INTERPOLATE",
                "ORDER BY events.event ASC WITH FILL FROM 0 TO 10 INTERPOLATE",
            ],
            [
                "interpolate_no_as",
                "select event, distinct_id from events order by event WITH FILL FROM 0 TO 10 INTERPOLATE (distinct_id)",
                "ORDER BY events.event ASC WITH FILL FROM 0 TO 10 INTERPOLATE (`events.distinct_id`)",
            ],
        ]
    )
    def test_select_order_by_with_fill(self, _name: str, query: str, expected_fragment: str):
        result = self._select(query)
        self.assertIn(expected_fragment, result)

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

    def test_select_limit_with_posthog_ai_context(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, limit_context=LimitContext.POSTHOG_AI)
        self.assertEqual(
            self._select("select 1 limit 1000", context=context),
            f"SELECT 1 LIMIT {MAX_SELECT_POSTHOG_AI_LIMIT}",
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

        self.assertEqual(
            self._select("select event from (select event from events offset 10)"),
            f"SELECT event AS event FROM (SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) OFFSET 10) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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

    @parameterized.expand(
        [
            (
                "grouping_sets",
                "select event, distinct_id, count() as c from events group by grouping sets ((event), (distinct_id), ())",
                "GROUP BY GROUPING SETS ((events.event), (events.distinct_id), ())",
            ),
            (
                "cube",
                "select event, distinct_id, count() as c from events group by cube(event, distinct_id)",
                "GROUP BY CUBE(events.event, events.distinct_id)",
            ),
            (
                "rollup",
                "select event, distinct_id, count() as c from events group by rollup(event, distinct_id)",
                "GROUP BY ROLLUP(events.event, events.distinct_id)",
            ),
        ]
    )
    def test_select_group_by_mode(self, _name: str, input_sql: str, expected_fragment: str):
        result = self._select(input_sql)
        self.assertIn(expected_fragment, result)

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
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE 0 LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )
        self.assertEqual(
            self._select(
                "SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 1 UNION ALL SELECT events.event FROM events WHERE 1 = 1"
            ),
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} UNION ALL SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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
            f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS}",
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
                "tupleElement(argMax(tuple(person_distinct_id_overrides.person_id), person_distinct_id_overrides.version), 1) AS person_id, "
                "person_distinct_id_overrides.distinct_id AS distinct_id FROM person_distinct_id_overrides WHERE "
                f"equals(person_distinct_id_overrides.team_id, {self.team.pk}) GROUP BY person_distinct_id_overrides.distinct_id "
                "HAVING ifNull(equals(tupleElement(argMax(tuple(person_distinct_id_overrides.is_deleted), person_distinct_id_overrides.version), 1), 0), 0) "
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
                "tupleElement(argMax(tuple(person_distinct_id_overrides.person_id), person_distinct_id_overrides.version), 1) AS person_id, "
                "person_distinct_id_overrides.distinct_id AS distinct_id FROM person_distinct_id_overrides WHERE "
                f"equals(person_distinct_id_overrides.team_id, {self.team.pk}) GROUP BY person_distinct_id_overrides.distinct_id "
                "HAVING ifNull(equals(tupleElement(argMax(tuple(person_distinct_id_overrides.is_deleted), person_distinct_id_overrides.version), 1), 0), 0) "
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
        context.database.get_table("events").fields["test_date"] = DateDatabaseField(name="test_date")  # type: ignore

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

    def test_assume_not_null_prevents_ifnull_wrapping_in_comparison(self):
        # base64Encode has no type signatures → returns UnknownType(nullable=True)
        # Without assumeNotNull, one side is considered nullable → comparison gets ifNull wrapping
        sql_without = self._expr("event = base64Encode('test')")
        self.assertIn("ifNull(", sql_without)

        # assumeNotNull forces nullable=False → both sides non-nullable → no wrapping
        sql_with = self._expr("event = assumeNotNull(base64Encode('test'))")
        self.assertNotIn("ifNull(", sql_with)
        self.assertTrue(sql_with.startswith("equals("))

    def test_assume_not_null_prevents_ifnull_wrapping_not_equals(self):
        sql_without = self._expr("event != base64Encode('test')")
        self.assertIn("ifNull(", sql_without)

        sql_with = self._expr("event != assumeNotNull(base64Encode('test'))")
        self.assertNotIn("ifNull(", sql_with)
        self.assertTrue(sql_with.startswith("notEquals("))

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

    @patch("posthog.hogql.printer.base.get_materialized_column_for_property")
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
        # Find the placeholder that holds our value (index varies with number of joins)
        trace_param_key = next((k for k, v in context.values.items() if v == "trace123"), None)
        self.assertIsNotNone(trace_param_key, "Expected 'trace123' to be recorded as a parameter value")
        self.assertIn(f"equals(events.`mat_$ai_trace_id`, %({trace_param_key})s)", sql)
        # Verify the equals for $ai_trace_id is NOT wrapped in ifNull (it appears directly in WHERE clause)
        self.assertIn("WHERE and(equals(events.team_id,", sql)

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
        trace1_param_key = next((k for k, v in context.values.items() if v == "trace1"), None)
        assert trace1_param_key is not None, "Expected 'trace1' to be recorded as a parameter value"
        trace2_param_key = next((k for k, v in context.values.items() if v == "trace2"), None)
        assert trace2_param_key is not None, "Expected 'trace2' to be recorded as a parameter value"
        self.assertIn(f"in(events.`mat_$ai_trace_id`, tuple(%({trace1_param_key})s, %({trace2_param_key})s))", sql)
        self.assertNotIn("ifNull(in", sql)

        # Verify other properties still get normal treatment
        mock_get_mat_col.return_value = None  # No materialized column for other props
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        sql = self._select("SELECT * FROM events WHERE properties.other_prop = 'value'", context)

        # Other properties should still have null handling with ifNull wrapping
        other_prop_param_key = next((k for k, v in context.values.items() if v == "other_prop"), None)
        assert other_prop_param_key is not None, "Expected 'other_prop' to be recorded as a parameter value"
        value_param_key = next((k for k, v in context.values.items() if v == "value"), None)
        assert value_param_key is not None, "Expected 'value' to be recorded as a parameter value"
        self.assertIn(
            f"ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %({other_prop_param_key})s), ''), 'null'), '^\"|\"$', ''), %({value_param_key})s), 0)",
            sql,
        )

    @patch("posthog.hogql.printer.base.get_materialized_column_for_property")
    def test_ai_session_id_optimizations(self, mock_get_mat_col):
        """Test that $ai_session_id gets special treatment for bloom filter index optimization"""

        from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

        mock_mat_col = MaterializedColumn(
            name="mat_$ai_session_id",
            details=MaterializedColumnDetails(
                table_column="properties", property_name="$ai_session_id", is_disabled=False
            ),
            is_nullable=True,
        )

        # Basic equality comparison - no ifNull wrapping
        mock_get_mat_col.return_value = mock_mat_col
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        sql = self._select("SELECT * FROM events WHERE properties.$ai_session_id = 'session123'", context)

        # Should generate: equals(mat_$ai_session_id, 'session123') without ifNull wrapper
        # Find the placeholder that holds our value (index varies with number of joins)
        session_param_key = next((k for k, v in context.values.items() if v == "session123"), None)
        assert session_param_key is not None, "Expected 'session123' to be recorded as a parameter value"
        self.assertIn(f"equals(events.`mat_$ai_session_id`, %({session_param_key})s)", sql)
        # Verify the equals for $ai_session_id is NOT wrapped in ifNull (it appears directly in WHERE clause)
        self.assertIn("WHERE and(equals(events.team_id,", sql)

        # With materialized column - no nullIf wrapping
        context = HogQLContext(team_id=self.team.pk)
        sql = self._expr("properties.$ai_session_id", context)

        # Should be: events.mat_$ai_session_id
        # NOT: nullIf(nullIf(events.mat_$ai_session_id, ''), 'null')
        self.assertEqual(sql.strip(), "events.`mat_$ai_session_id`")
        self.assertNotIn("nullIf", sql)

        # IN operations - no ifNull wrapping
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql = self._select("SELECT * FROM events WHERE properties.$ai_session_id IN ('session1', 'session2')", context)

        # Should generate clean IN without ifNull wrapper
        session1_param_key = next((k for k, v in context.values.items() if v == "session1"), None)
        assert session1_param_key is not None, "Expected 'session1' to be recorded as a parameter value"
        session2_param_key = next((k for k, v in context.values.items() if v == "session2"), None)
        assert session2_param_key is not None, "Expected 'session2' to be recorded as a parameter value"
        self.assertIn(
            f"in(events.`mat_$ai_session_id`, tuple(%({session1_param_key})s, %({session2_param_key})s))", sql
        )
        self.assertNotIn("ifNull(in", sql)

    def test_field_nullable_like(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=Database())
        context.database.get_table("events").fields["nullable_field"] = StringDatabaseField(  # type: ignore
            name="nullable_field", nullable=True
        )
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
        context.database.get_table("events").fields["nullable_field"] = StringDatabaseField(  # type: ignore
            name="nullable_field", nullable=True
        )
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
        context.database.get_table("events").fields["nullable_field"] = StringDatabaseField(  # type: ignore
            name="nullable_field", nullable=True
        )
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
        context.database.get_table("events").fields["nullable_field"] = StringDatabaseField(  # type: ignore
            name="nullable_field", nullable=True
        )
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
        printed = self._print("SELECT 1 FROM events", settings=HogQLGlobalSettings(max_execution_time=10))
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_print_query_level_settings(self):
        query = parse_select("SELECT 1 FROM events")
        assert isinstance(query, ast.SelectQuery)
        query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        printed, _ = prepare_and_print_ast(
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
        printed, _ = prepare_and_print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT 1 FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS optimize_aggregation_in_order=1, readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_table_top_level_settings_added_to_query(self):
        printed = self._print("SELECT job_id FROM preaggregation_results")
        assert "load_balancing='in_order'" in printed

    def test_table_top_level_settings_not_added_for_regular_tables(self):
        printed = self._print("SELECT event FROM events")
        assert "load_balancing" not in printed

    def test_table_top_level_settings_deduplication(self):
        printed = self._print(
            "SELECT a.job_id, b.job_id "
            "FROM preaggregation_results a "
            "JOIN experiment_exposures_preaggregated b ON a.job_id = b.job_id"
        )
        assert printed.count("load_balancing") == 1

    def test_table_top_level_settings_conflict_between_tables(self):
        db = Database()
        db.get_table("preaggregation_results").top_level_settings = HogQLQuerySettings(load_balancing="round_robin")
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query_both = parse_select(
            "SELECT a.job_id, b.job_id "
            "FROM preaggregation_results a "
            "JOIN experiment_exposures_preaggregated b ON a.job_id = b.job_id"
        )
        with self.assertRaises(QueryError) as cm:
            prepare_and_print_ast(query_both, context, "clickhouse")
        assert "Conflicting" in str(cm.exception)

    def test_table_top_level_settings_conflict_with_query_settings(self):
        query = parse_select("SELECT job_id FROM preaggregation_results")
        assert isinstance(query, ast.SelectQuery)
        query.settings = HogQLQuerySettings(load_balancing="round_robin")
        with self.assertRaises(QueryError) as cm:
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                "clickhouse",
            )
        assert "Conflicting" in str(cm.exception)

    def test_table_top_level_settings_conflict_with_global_settings(self):
        query = parse_select("SELECT job_id FROM preaggregation_results")
        with self.assertRaises(QueryError) as cm:
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                "clickhouse",
                settings=HogQLGlobalSettings(load_balancing="round_robin"),
            )
        assert "Conflicting" in str(cm.exception)

    def test_table_top_level_settings_same_value_in_query_settings(self):
        query = parse_select("SELECT job_id FROM preaggregation_results")
        assert isinstance(query, ast.SelectQuery)
        query.settings = HogQLQuerySettings(load_balancing="in_order")
        printed, _ = prepare_and_print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        assert "load_balancing='in_order'" in printed
        assert printed.count("load_balancing") == 1

    def test_table_top_level_settings_with_global_settings_single_clause(self):
        query = parse_select("SELECT job_id FROM preaggregation_results")
        printed, _ = prepare_and_print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            settings=HogQLGlobalSettings(max_execution_time=30),
        )
        assert "load_balancing='in_order'" in printed
        assert printed.count("SETTINGS") == 1
        assert printed.count("load_balancing") == 1

    def test_subquery_table_settings_bubble_up(self):
        printed = self._print("SELECT job_id FROM (SELECT job_id FROM preaggregation_results)")
        assert "load_balancing='in_order'" in printed

    def test_warehouse_csv_table_with_double_quotes_setting(self):
        from posthog.hogql.database.models import TableNode
        from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable

        csv_table = HogQLDataWarehouseTable(
            name="csv_table",
            url="https://example.com/test.csv",
            format="CSVWithNames",
            fields={"col1": StringDatabaseField(name="col1")},
            structure="`col1` String",
            top_level_settings=HogQLQuerySettings(format_csv_allow_double_quotes=True),
        )
        db = Database()
        root = TableNode()
        root.add_child(TableNode(name="csv_table", table=csv_table))
        db._add_warehouse_tables(root)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        query = parse_select("SELECT col1 FROM csv_table")
        printed, _ = prepare_and_print_ast(query, context, "clickhouse")
        assert "format_csv_allow_double_quotes=1" in printed

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
        printed = self._print(
            "select * from (SELECT timestamp, timestamp FROM events)",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT timestamp AS timestamp FROM (SELECT toTimeZone(events.timestamp, %(hogql_val_0)s), "
            f"toTimeZone(events.timestamp, %(hogql_val_1)s) AS timestamp FROM events WHERE equals(events.team_id, {self.team.pk})) "
            f"LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_print_hidden_aliases_column_override(self):
        printed = self._print(
            "select * from (SELECT timestamp as event, event FROM events)",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT event AS event FROM (SELECT toTimeZone(events.timestamp, %(hogql_val_0)s) AS event, "
            f"event FROM events WHERE equals(events.team_id, {self.team.pk})) "
            f"LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_print_hidden_aliases_properties(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")

        printed = self._print(
            "select * from (SELECT properties.$browser FROM events)",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT `$browser` AS `$browser` FROM (SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` "
            f"FROM events WHERE equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS} "
            f"SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_print_hidden_aliases_double_property(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")

        printed = self._print(
            "select * from (SELECT properties.$browser, properties.$browser FROM events)",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            printed,
            f"SELECT `$browser` AS `$browser` FROM (SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null'), "
            f"nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` "  # only the second one gets the alias
            f"FROM events WHERE equals(events.team_id, {self.team.pk})) LIMIT {MAX_SELECT_RETURNED_ROWS} "
            f"SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    def test_lookup_domain_type(self):
        printed = self._print(
            "select lookupDomainType('www.google.com') as domain from events",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'domain_type', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')), "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'domain_type', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS domain "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        ) == printed

    def test_lookup_paid_source_type(self):
        printed = self._print(
            "select lookupPaidSourceType('google') as source from events",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')) , "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS source "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        ) == printed

    def test_lookup_paid_medium_type(self):
        printed = self._print(
            "select lookupPaidMediumType('social') as medium from events",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_paid', "
            "(coalesce(%(hogql_val_0)s, ''), 'medium')) AS medium "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        ) == printed

    def test_lookup_organic_source_type(self):
        printed = self._print(
            "select lookupOrganicSourceType('google') as source  from events",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT coalesce(dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(coalesce(%(hogql_val_0)s, ''), 'source')), "
            "dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(cutToFirstSignificantSubdomain(coalesce(%(hogql_val_0)s, '')), 'source'))) AS source "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000 SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, "
            "max_ast_elements=4000000, "
            "max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        ) == printed

    def test_lookup_organic_medium_type(self):
        printed = self._print(
            "select lookupOrganicMediumType('social') as medium from events",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            "SELECT dictGetOrNull('posthog_test.channel_definition_dict', 'type_if_organic', "
            "(coalesce(%(hogql_val_0)s, ''), 'medium')) AS medium "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        ) == printed

    def test_currency_conversion(self):
        printed = self._print(
            "select convertCurrency('USD', 'EUR', 100, toDate('2021-01-01')) as currency",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            (
                f"SELECT if(equals(%(hogql_val_0)s, %(hogql_val_1)s), toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10)) = 0, toDecimal64(0, 10), multiplyDecimal(divideDecimal(toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10)) = 0, toDecimal64(1, 10), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10)))), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_1)s, toDateOrNull(%(hogql_val_2)s), toDecimal64(0, 10))))) AS currency "
                "LIMIT 50000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
            ),
            printed,
        )

    def test_currency_conversion_without_date(self):
        printed = self._print(
            "select convertCurrency('USD', 'EUR', 100) as currency",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            (
                f"SELECT if(equals(%(hogql_val_0)s, %(hogql_val_1)s), toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, today(), toDecimal64(0, 10)) = 0, toDecimal64(0, 10), multiplyDecimal(divideDecimal(toDecimal64(100, 10), if(dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, today(), toDecimal64(0, 10)) = 0, toDecimal64(1, 10), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_0)s, today(), toDecimal64(0, 10)))), dictGetOrDefault(`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', %(hogql_val_1)s, today(), toDecimal64(0, 10))))) AS currency "
                "LIMIT 50000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
            ),
            printed,
        )

    def test_sortable_semver(self):
        # Also test different capitalizations
        printed = self._print(
            """
                SELECT
                  sortableSemVer('1.2.3') AS semver1,
                  sortableSemver('1.2.3') AS semver2,
                  sortablesemver('1.2.3') AS semver3,
                  sOrTaBlEsEmVeR('1.2.3') AS semver4
            """,
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        self.assertEqual(
            (
                f"SELECT arrayMap(x -> toInt64OrZero(x),  splitByChar('.', extract(assumeNotNull(%(hogql_val_0)s), '(\\d+(\\.\\d+)+)'))) AS semver1, "
                f"arrayMap(x -> toInt64OrZero(x),  splitByChar('.', extract(assumeNotNull(%(hogql_val_1)s), '(\\d+(\\.\\d+)+)'))) AS semver2, "
                f"arrayMap(x -> toInt64OrZero(x),  splitByChar('.', extract(assumeNotNull(%(hogql_val_2)s), '(\\d+(\\.\\d+)+)'))) AS semver3, "
                f"arrayMap(x -> toInt64OrZero(x),  splitByChar('.', extract(assumeNotNull(%(hogql_val_3)s), '(\\d+(\\.\\d+)+)'))) AS semver4 "
                "LIMIT 50000 SETTINGS readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
            ),
            printed,
        )

    def test_get_survey_response(self):
        # Test with just question index (0) - dynamic key
        result = execute_hogql_query(
            team=self.team,
            query="SELECT getSurveyResponse(0) FROM events",
        )
        assert result.clickhouse is not None
        # Dynamic key (no question_id) uses concat for key construction
        self.assertIn("coalesce", result.clickhouse)
        self.assertIn("nullIf", result.clickhouse)
        self.assertIn("concat", result.clickhouse)
        # Always uses JSONExtractString for consistent String return type
        self.assertIn("JSONExtractString", result.clickhouse)

        # Test with question index and specific ID - static key
        result = execute_hogql_query(
            team=self.team,
            query="SELECT getSurveyResponse(1, 'question123') FROM events",
        )
        assert result.clickhouse is not None
        # Static key also uses JSONExtractString for type consistency
        self.assertIn("coalesce", result.clickhouse)
        self.assertIn("nullIf", result.clickhouse)
        self.assertIn("JSONExtractString", result.clickhouse)

        # Test with multiple choice question
        result = execute_hogql_query(
            team=self.team,
            query="SELECT getSurveyResponse(2, 'abc123', true) FROM events",
        )
        assert result.clickhouse is not None
        # Multiple choice uses if() with JSONHas and JSONExtractArrayRaw
        self.assertIn("JSONHas", result.clickhouse)
        self.assertIn("JSONExtractArrayRaw", result.clickhouse)
        self.assertIn("if(", result.clickhouse)

    def test_get_survey_response_with_numeric_property_type(self):
        """Test that getSurveyResponse returns consistent types even when property has Numeric type.

        Regression test for a bug where PropertySwapper would wrap the index-based
        property access with toFloat() when $survey_response had type=Numeric in
        PropertyDefinition, causing a ClickHouse type mismatch error:
        "There is no supertype for types String, Float64"
        """
        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name="$survey_response",
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )

        # This should NOT raise a ClickHouse error about type mismatch
        # Before the fix, this would fail with:
        # "There is no supertype for types String, Float64 because some of them
        # are String/FixedString/Enum and some of them are not"
        result = execute_hogql_query(
            team=self.team,
            query="SELECT getSurveyResponse(0) FROM events",
        )

        # Query should execute successfully (even with no results)
        assert result.clickhouse is not None
        # Both branches of coalesce should return String type (via JSONExtractString)
        self.assertIn("JSONExtractString", result.clickhouse)
        # Should NOT contain Float64 casting which would cause type mismatch
        self.assertNotIn("accurateCastOrNull", result.clickhouse)
        self.assertNotIn("Float64", result.clickhouse)

    def test_unique_survey_submissions_filter(self):
        printed = self._print(
            "select uuid from events where uniqueSurveySubmissionsFilter('survey123')",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        # Should contain subquery with argMax for deduplication
        # String literals are parameterized, so check for structure instead
        self.assertIn("argMax", printed)
        self.assertIn("in(events.uuid", printed)
        self.assertIn("SELECT argMax(events.uuid", printed)
        self.assertIn("FROM events WHERE", printed)
        self.assertIn("GROUP BY", printed)
        self.assertIn("JSONExtractRaw(events.properties", printed)

    def test_unique_survey_submissions_filter_with_timestamps(self):
        printed = self._print(
            "select uuid from events where uniqueSurveySubmissionsFilter('survey123', '2025-01-01', '2025-01-31')",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )

        self.assertIn("events.timestamp", printed)
        self.assertIn("greaterOrEquals", printed)
        self.assertIn("lessOrEquals", printed)

    def test_unique_survey_submissions_filter_with_datetime_placeholders(self):
        printed = self._print(
            "select uuid from events where uniqueSurveySubmissionsFilter('survey123', {start_date}, {end_date})",
            placeholders={
                "start_date": ast.Constant(value=datetime(2025, 1, 1, 0, 0, 0)),
                "end_date": ast.Constant(value=datetime(2025, 1, 31, 23, 59, 59)),
            },
            settings=HogQLGlobalSettings(max_execution_time=10),
        )

        self.assertIn("events.timestamp", printed)
        self.assertIn("greaterOrEquals", printed)
        self.assertIn("lessOrEquals", printed)

    def test_override_timezone(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=Database(None, WeekStartDay.SUNDAY),
        )
        context.database.get_table("events").fields["test_date"] = DateDatabaseField(name="test_date")  # type: ignore

        self.assertEqual(
            self._select(
                """
                SELECT toDateTime(timestamp)               as ts,
                       toDateTime(timestamp, 'US/Pacific') as tsz,
                       now()                               as now,
                       now('US/Pacific')                   as nowz
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
        printed = self._print(
            "select trim(LEADING 'xy' FROM 'media') as a, trim(TRAILING 'xy' FROM 'media') as b, trim(BOTH 'xy' FROM 'media') as c",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert printed == (
            f"SELECT trim(LEADING %(hogql_val_1)s FROM %(hogql_val_0)s) AS a, trim(TRAILING %(hogql_val_3)s FROM %(hogql_val_2)s) AS b, trim(BOTH %(hogql_val_5)s FROM %(hogql_val_4)s) AS c LIMIT {MAX_SELECT_RETURNED_ROWS} SETTINGS "
            "readonly=2, max_execution_time=10, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"
        )
        printed2 = self._print(
            "select trimLeft('media', 'xy') as a, trimRight('media', 'xy') as b, trim('media', 'xy') as c",
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
        printed = self._print(
            "select persons.id as person_id from events join persons on persons.id = events.person_id and persons.id in (1,2,3)",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed

    def test_dont_inline_persons(self):
        printed = self._print(
            "select persons.id as person_id from events join persons on persons.id = events.person_id and persons.id = 1",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE equals(person.team_id, {self.team.pk})" in printed

    def test_inline_persons_alias(self):
        printed = self._print(
            """
            select p1.id as p1_id
            from events
                     join persons as p1 on p1.id = events.person_id and p1.id in (1, 2, 3)
            """,
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed

    def test_two_joins(self):
        printed = self._print(
            """
            select p1.id as p1_id, p2.id as p2_id
            from events
                     join persons as p1 on p1.id = events.person_id and p1.id in (1, 2, 3)
                     join persons as p2 on p2.id = events.person_id and p2.id in (4, 5, 6)
            """,
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(1, 2, 3)))" in printed
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(4, 5, 6)))" in printed

    def test_two_clauses(self):
        printed = self._print(
            """
            select p1.id as p1_id, p2.id as p2_id
            from events
                     join persons as p1 on p1.id in (7, 8, 9) and p1.id = events.person_id and p1.id in (1, 2, 3)
                     join persons as p2 on p2.id = events.person_id and p2.id in (4, 5, 6)
            """,
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
        assert (
            f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(7, 8, 9)), in(id, tuple(1, 2, 3)))"
            in printed
        )
        assert f"AS id FROM person WHERE and(equals(person.team_id, {self.team.pk}), in(id, tuple(4, 5, 6)))" in printed

    def test_print_hogql_aggregation_function_uses_hogql_function_names(self):
        query = parse_expr("avgArray([1, 2, 3])")
        printed, _ = prepare_and_print_ast(query, HogQLContext(team_id=self.team.pk), dialect="hogql")
        assert printed == "avgArray([1, 2, 3])"

    def test_print_percentage_call_alias(self):
        printed = self._print("SELECT concat('%', 'word', '%') LIMIT 1")

        assert (
            printed
            == "SELECT concat(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s) AS `concat('', 'word', '')` LIMIT 1"
        )

    def test_print_hogql_output_format(self):
        printed = self._print(
            "select 1 limit 1",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
            dialect="hogql",
        )
        assert printed == "SELECT 1 LIMIT 1"

    def test_print_clickhouse_output_format(self):
        printed = self._print(
            "select 1 limit 1",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
        )
        assert printed == "SELECT 1 LIMIT 1 FORMAT ArrowStream"

    def test_print_clickhouse_output_format_union(self):
        printed = self._print(
            "select 1 limit 1 union all select 2 limit 1",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
        )
        assert printed == "SELECT 1 LIMIT 1 UNION ALL SELECT 2 LIMIT 1 FORMAT ArrowStream"

    def test_print_clickhouse_output_format_union_with_nested_union_subquery(self):
        printed = self._print(
            "select * from (select 1 as num union all select 2 as num) limit 2",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True, output_format="ArrowStream"),
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
        printed = self._print("SELECT arrayReduce('sum', [1, 2, 3])")
        assert printed == (
            "SELECT arrayReduce(%(hogql_val_0)s, [1, 2, 3]) AS `arrayReduce('sum', [1, 2, 3])` LIMIT 50000"
        )

    def test_dropped_hidden_alias_still_reserves_type_based_name(self):
        subquery_type = ast.SelectQueryType(
            columns={"toDate(period_end)": ast.DateType(), "period_end": ast.DateType()}
        )

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="toDate(period_end)",
                    expr=ast.Field(
                        chain=["toDate(period_end)"],
                        type=ast.FieldType(name="toDate(period_end)", table_type=subquery_type),
                    ),
                    hidden=True,
                ),
                ast.Call(
                    name="toDate",
                    args=[
                        ast.Field(
                            chain=["period_end"],
                            type=ast.FieldType(name="period_end", table_type=subquery_type),
                        )
                    ],
                ),
                ast.Alias(
                    alias="toDate(period_end)",
                    expr=ast.Field(
                        chain=["toDate(period_end)"],
                        type=ast.FieldType(name="toDate(period_end)", table_type=subquery_type),
                        from_asterisk=True,
                    ),
                    hidden=True,
                ),
            ]
        )

        printed = print_prepared_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
        )

        assert (
            printed
            == "SELECT `toDate(period_end)`, toDate(period_end), `toDate(period_end)` AS `toDate(period_end)` LIMIT 50000"
        )

    def test_can_call_parametric_function_from_placeholder(self):
        printed = self._print("SELECT arrayReduce({f}, [1, 2, 3])", placeholders={"f": ast.Constant(value="sum")})
        assert printed == (
            "SELECT arrayReduce(%(hogql_val_0)s, [1, 2, 3]) AS `arrayReduce('sum', [1, 2, 3])` LIMIT 50000"
        )

    def test_fails_on_parametric_function_with_no_arguments(self):
        query = parse_select("SELECT arrayReduce()")
        with pytest.raises(QueryError, match="Missing arguments in function 'arrayReduce'"):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_numeric(self):
        query = parse_select("SELECT arrayReduce(1, [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got IntegerType '1'"
        ):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_lambda(self):
        query = parse_select("SELECT arrayReduce(x -> x, [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got Lambda"
        ):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_expression(self):
        query = parse_select("SELECT arrayReduce('ev' + 'il', [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Expected constant string as first arg in function 'arrayReduce', got ArithmeticOperation"
        ):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_missing(self):
        query = parse_select("SELECT arrayReduce('evil', [1, 2, 3])")
        with pytest.raises(QueryError, match="Invalid parametric function in 'arrayReduce', 'evil' is not supported."):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_invalid(self):
        query = parse_select("SELECT arrayReduce('array_agg', [1, 2, 3])")
        with pytest.raises(
            QueryError, match="Invalid parametric function in 'arrayReduce', 'array_agg' is not supported."
        ):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_parametric_function_with_evil_placeholder(self):
        query = parse_select("SELECT arrayReduce({f}, [1, 2, 3])", placeholders={"f": ast.Constant(value="evil")})
        with pytest.raises(QueryError, match="Invalid parametric function in 'arrayReduce', 'evil' is not supported."):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_fails_on_placeholder_macro_expansion_depth_limit(self):
        query = parse_select(
            """
            SELECT date_part('year', date_part('year', date_part('year', date_part('year', date_part('year', date_part('year', date_part('year', date_part('year', date_part('year', now())))))))))
            """
        )
        with pytest.raises(QueryError, match="exceeded maximum placeholder macro depth"):
            prepare_and_print_ast(
                query,
                HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="clickhouse",
            )

    def test_date_part_macro_does_not_expand_exponentially(self):
        sql = self._select("SELECT date_part('year', date_part('year', date_part('year', now())))")

        assert "arrayMap((part, dt) -> multiIf" in sql
        assert sql.count("now()") == 1
        assert len(sql) < 3_000

    def test_team_id_guarding_events(self):
        sql = self._select(
            "SELECT event FROM events",
        )
        assert (
            sql == f"SELECT events.event AS event FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 50000"
        )

    @parameterized.expand(
        [
            ("global_joins_with_optimize", True, True),
            ("global_joins_without_optimize", True, False),
            ("no_global_joins_with_optimize", False, True),
            ("no_global_joins_without_optimize", False, False),
        ]
    )
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_with_cte(self, name, using_global_joins, optimize_projections):
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
            modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
            context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
            printed = self._select(
                """
                WITH some_remote_table AS
                         (SELECT *
                          FROM test_table)
                SELECT event
                FROM events
                         JOIN some_remote_table ON events.event = toString(some_remote_table.id)""",
                context=context,
            )

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
            printed = self._select(
                """
                                   WITH some_remote_table AS
                                            (SELECT e.event, t.id
                                             FROM events e
                                                      JOIN test_table t on toString(t.id) = e.event)
                                   SELECT some_remote_table.event
                                   FROM events
                                            JOIN some_remote_table ON events.event = toString(some_remote_table.id)"""
            )

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
            printed = self._select(
                """
                                   SELECT e.event, s.event, t.id
                                   FROM events e
                                            JOIN (SELECT event from events) as s ON e.event = s.event
                                            LEFT JOIN test_table t on e.event = toString(t.id)"""
            )

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

            printed = self._select(
                """
                                   SELECT event
                                   FROM events
                                   WHERE properties.$browser IN (SELECT id
                                                                 FROM test_table)"""
            )

            if using_global_joins:
                assert "globalIn" in printed
            else:
                assert "globalIn" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand(
        [
            (SessionTableVersion.V1, "IN", "globalIn"),
            (SessionTableVersion.V1, "NOT IN", "globalNotIn"),
            (SessionTableVersion.V2, "IN", "globalIn"),
            (SessionTableVersion.V2, "NOT IN", "globalNotIn"),
            (SessionTableVersion.V3, "IN", "globalIn"),
            (SessionTableVersion.V3, "NOT IN", "globalNotIn"),
        ]
    )
    def test_sessions_filter_by_event_subquery_uses_global_in(self, version, op, expected):
        modifiers = HogQLQueryModifiers(sessionTableVersion=version)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        printed = self._select(
            f"""
            SELECT session_id
            FROM sessions
            WHERE session_id {op} (SELECT $session_id FROM events WHERE event = 'payment_confirm_clicked')
            """,
            context=context,
        )
        assert expected in printed, f"expected {expected} in:\n{printed}"

    @parameterized.expand([("IN", "globalIn"), ("NOT IN", "globalNotIn")])
    def test_sessions_filter_by_event_subquery_uses_global_in_with_alias(self, op, expected):
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V3)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        printed = self._select(
            f"""
            SELECT s.session_id
            FROM sessions AS s
            WHERE s.session_id {op} (SELECT $session_id FROM events)
            """,
            context=context,
        )
        assert expected in printed, f"expected {expected} in:\n{printed}"

    @parameterized.expand([("IN", "globalIn"), ("NOT IN", "globalNotIn")])
    def test_events_filter_by_sessions_subquery_uses_global_in(self, op, expected):
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V3)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        printed = self._select(
            f"""
            SELECT uuid
            FROM events
            WHERE $session_id {op} (SELECT session_id FROM sessions)
            """,
            context=context,
        )
        assert expected in printed, f"expected {expected} in:\n{printed}"

    def test_events_in_subquery_not_promoted(self):
        # Non-sessions case: no cross-cluster hazard, keep plain in.
        printed = self._select(
            "SELECT uuid FROM events WHERE event IN (SELECT event FROM events WHERE timestamp > now() - toIntervalDay(1))"
        )
        assert "globalIn" not in printed, f"did not expect globalIn in:\n{printed}"

    @parameterized.expand(
        [
            ("global_joins_with_optimize", True, True),
            ("global_joins_without_optimize", True, False),
            ("no_global_joins_with_optimize", False, True),
            ("no_global_joins_without_optimize", False, False),
        ]
    )
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_s3_tables_global_join_anonymous_tables(self, name, using_global_joins, optimize_projections):
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

            modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
            context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
            printed = self._select(
                """
                select e.event, ij.remote_id
                from events e
                         inner join (select *
                                     from (select p.id as person_id, rt.id as remote_id
                                           from persons p
                                                    left join (select *
                                                               from test_table) rt on rt.id = p.id)) as ij
                                    on e.event = ij.remote_id""",
                context=context,
            )

            if using_global_joins:
                assert "GLOBAL INNER JOIN" in printed
            else:
                assert "GLOBAL INNER JOIN" not in printed

            assert clean_varying_query_parts(printed, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([("with_optimize_projections", True), ("without_optimize_projections", False)])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_projection_pushdown_simple_asterisk_subquery(self, name, optimize_projections):
        """Test that SELECT event FROM (SELECT * FROM events) prunes unused columns when optimized"""
        modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        result = self._select("SELECT event FROM (SELECT * FROM events) AS sub", context)

        assert clean_varying_query_parts(result, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([("with_optimize_projections", True), ("without_optimize_projections", False)])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_projection_pushdown_nested_subqueries(self, name, optimize_projections):
        """Test projection pushdown through multiple nested subquery levels"""
        modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        result = self._select(
            """
            SELECT event
            FROM (SELECT *
                  FROM (SELECT *
                        FROM events) AS inner) AS outer
            """,
            context,
        )

        assert clean_varying_query_parts(result, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([("with_optimize_projections", True), ("without_optimize_projections", False)])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_projection_pushdown_preserves_where_columns(self, name, optimize_projections):
        """Test that columns used in WHERE clauses are preserved even with optimization"""
        modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        result = self._select(
            """
            SELECT event
            FROM (SELECT * FROM events) AS sub
            WHERE distinct_id = 'test'
            """,
            context,
        )

        assert clean_varying_query_parts(result, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([("with_optimize_projections", True), ("without_optimize_projections", False)])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_projection_pushdown_preserves_join_columns(self, name, optimize_projections):
        """Test that columns used in JOIN conditions are preserved"""
        modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        result = self._select(
            """
            SELECT e.event
            FROM (SELECT * FROM events) AS e
                     LEFT JOIN persons ON persons.id = e.person_id
            """,
            context,
        )

        assert clean_varying_query_parts(result, replace_all_numbers=False) == self.snapshot  # type: ignore

    @parameterized.expand([("with_optimize_projections", True), ("without_optimize_projections", False)])
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_projection_pushdown_no_asterisk_unchanged(self, name, optimize_projections):
        """Test that queries without asterisks remain unchanged"""
        modifiers = HogQLQueryModifiers(optimizeProjections=optimize_projections)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        result = self._select("SELECT event FROM (SELECT event, distinct_id FROM events) AS sub", context)

        assert clean_varying_query_parts(result, replace_all_numbers=False) == self.snapshot  # type: ignore

    def test_cte_with_alias_in_join_clickhouse(self):
        """Test that CTETableAliasType properly prints in ClickHouse dialect with qualified fields"""
        result = self._select(
            """
            WITH
                exposures AS (SELECT event AS person_id, timestamp AS exposure_time FROM events),
                conversions AS (SELECT event AS person_id, timestamp AS conversion_time FROM events)
            SELECT
                e.person_id,
                e.exposure_time,
                c.conversion_time
            FROM exposures AS e
            LEFT JOIN conversions AS c ON e.person_id = c.person_id AND c.conversion_time >= e.exposure_time
            """
        )

        # The key assertion: JOIN constraint fields should be qualified with CTE aliases
        self.assertIn("equals(e.person_id, c.person_id)", result)
        # timestamp fields get wrapped in toTimeZone, but the important part is the alias qualification
        self.assertIn("c.conversion_time", result)
        self.assertIn("e.exposure_time", result)
        # Verify the greaterOrEquals comparison exists with the qualified fields
        self.assertIn("greaterOrEquals(toTimeZone(c.conversion_time", result)
        self.assertIn("toTimeZone(e.exposure_time", result)
        # Verify CTE aliasing in FROM/JOIN clauses
        self.assertIn("FROM exposures AS e", result)
        self.assertIn("LEFT JOIN conversions AS c", result)

    def test_cte_non_aliased_with_aliased_join_clickhouse(self):
        """Test mixing non-aliased and aliased CTEs in ClickHouse output"""
        result = self._select(
            """
            WITH users AS (SELECT event AS user_id, timestamp FROM events)
            SELECT users.user_id, u2.user_id, users.timestamp
            FROM users
            LEFT JOIN users AS u2 ON users.user_id = u2.user_id
            """
        )

        # Non-aliased CTE: fields qualified with CTE name
        self.assertIn("users.user_id", result)
        self.assertIn("users.timestamp", result)
        # Aliased CTE: fields qualified with alias
        self.assertIn("u2.user_id", result)
        # JOIN constraint should have both
        self.assertIn("equals(users.user_id, u2.user_id)", result)
        # Verify table references
        self.assertIn("FROM users", result)
        self.assertIn("LEFT JOIN users AS u2", result)

    def test_cte_multiple_aliases_same_cte_clickhouse(self):
        """Test that the same CTE can be joined multiple times with different aliases"""
        result = self._select(
            """
            WITH base AS (SELECT event AS id FROM events)
            SELECT b1.id, b2.id, b3.id
            FROM base AS b1
            LEFT JOIN base AS b2 ON b1.id = b2.id
            LEFT JOIN base AS b3 ON b2.id = b3.id
            """
        )

        # All three aliases should be present and properly qualified
        self.assertIn("b1.id", result)
        self.assertIn("b2.id", result)
        self.assertIn("b3.id", result)
        # JOIN constraints should use the right aliases
        self.assertIn("equals(b1.id, b2.id)", result)
        self.assertIn("equals(b2.id, b3.id)", result)
        # Table aliases in FROM/JOIN
        self.assertIn("FROM base AS b1", result)
        self.assertIn("LEFT JOIN base AS b2", result)
        self.assertIn("LEFT JOIN base AS b3", result)

    def test_final_keyword_not_supported(self):
        with self.assertRaises(QueryError) as e:
            self._select("SELECT * FROM events FINAL")
        self.assertEqual("The FINAL keyword is not supported in HogQL as it causes slow queries", str(e.exception))

        with self.assertRaises(QueryError) as e:
            self._select("SELECT * FROM events FINAL WHERE timestamp > '2026-01-01'")
        self.assertEqual("The FINAL keyword is not supported in HogQL as it causes slow queries", str(e.exception))

    @parameterized.expand(
        [
            # Integer types
            ("int", "event::int", "toInt64(events.event)"),
            ("integer", "event::integer", "toInt64(events.event)"),
            ("int_upper", "event::INT", "toInt64(events.event)"),
            # Float types
            ("float", "event::float", "toFloat64(events.event)"),
            ("double", "event::double", "toFloat64(events.event)"),
            ("double_precision", 'event::"double precision"', "toFloat64(events.event)"),
            ("real", "event::real", "toFloat64(events.event)"),
            # String types
            ("text", "event::text", "toString(events.event)"),
            ("varchar", "event::varchar", "toString(events.event)"),
            ("char", "event::char", "toString(events.event)"),
            ("string", "event::string", "toString(events.event)"),
            # Boolean types
            ("boolean", "event::boolean", "toBoolean(events.event)"),
            ("bool", "event::bool", "toBoolean(events.event)"),
            # Date type
            ("date", "event::date", "toDate(events.event)"),
            # Constant cast
            ("const_int", "'123'::int", "toInt64(%(hogql_val_0)s)"),
            ("const_float", "123.45::float", "toFloat64(123.45)"),
        ]
    )
    def test_postgres_style_cast(self, name, expr, expected):
        self.assertEqual(self._expr(expr), expected)

    def test_postgres_style_cast_datetime(self):
        # DateTime types include timezone, test separately
        self.assertIn("toDateTime(events.event", self._expr("event::datetime"))
        self.assertIn("toDateTime(events.event", self._expr("event::timestamp"))
        self.assertIn("toDateTime(events.event", self._expr("event::timestamptz"))

    def test_postgres_style_cast_unsupported_type(self):
        with self.assertRaises(QueryError) as ctx:
            self._expr("event::unsupported_type")
        self.assertIn("Unsupported type cast", str(ctx.exception))

    def test_cte_materialization_hint_not_supported(self):
        with self.assertRaises(ImpossibleASTError) as ctx:
            self._select(
                """
                WITH some_cte AS MATERIALIZED (SELECT event FROM events)
                SELECT event FROM some_cte
                """,
            )
        self.assertIn("not supported", str(ctx.exception))

    def test_cte_column_name_list_not_supported(self):
        with self.assertRaises(NotImplementedError):
            self._select(
                "WITH stats(a, b) AS (SELECT event, timestamp FROM events) SELECT a, b FROM stats",
            )

    def test_cte_using_key_not_supported(self):
        with self.assertRaises(ImpossibleASTError) as ctx:
            self._select(
                "WITH x USING KEY (a) AS (SELECT 1 AS a, 2 AS b) SELECT * FROM x",
            )
        self.assertIn("not supported", str(ctx.exception))

    def test_projection_pushdown_cte_with_lazy_table_join(self):
        modifiers = HogQLQueryModifiers(optimizeProjections=True)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        # Pruning the CTE should not leave stale LazyTableType references
        # in SelectQueryType.columns that cause KeyError during lazy table resolution
        self._select(
            """
            WITH combined AS (SELECT * FROM persons LIMIT 10)
            SELECT 1 FROM events AS e LEFT JOIN combined AS c ON e.distinct_id = c.id
            """,
            context=context,
        )

    @parameterized.expand(
        [
            (
                "eq_direct_field",
                "$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'",
                "equals(events.`$session_id_uuid`, toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')))",
            ),
            (
                "neq_direct_field",
                "$session_id != 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'",
                "notEquals(events.`$session_id_uuid`, toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')))",
            ),
            (
                "eq_constant_on_left",
                "'a1b2c3d4-e5f6-7890-abcd-ef1234567890' = $session_id",
                "equals(events.`$session_id_uuid`, toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')))",
            ),
            (
                "eq_property_access",
                "properties.$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'",
                "equals(events.`$session_id_uuid`, toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')))",
            ),
            (
                "in_operation",
                "$session_id IN ('a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'b2c3d4e5-f6a7-8901-bcde-f12345678901')",
                "in(events.`$session_id_uuid`, tuple(toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')), toUInt128(accurateCastOrNull(%(hogql_val_1)s, 'UUID'))))",
            ),
            (
                "not_in_operation",
                "$session_id NOT IN ('a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'b2c3d4e5-f6a7-8901-bcde-f12345678901')",
                "notIn(events.`$session_id_uuid`, tuple(toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')), toUInt128(accurateCastOrNull(%(hogql_val_1)s, 'UUID'))))",
            ),
            (
                "eq_uppercase_uuid",
                "$session_id = 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890'",
                "equals(events.`$session_id_uuid`, toUInt128(accurateCastOrNull(%(hogql_val_0)s, 'UUID')))",
            ),
        ]
    )
    def test_session_id_uuid_optimization(self, _name, expr, expected):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            ("non_uuid_string", "$session_id = 'not-a-uuid'"),
            ("non_string_constant", "$session_id = 123"),
            ("in_with_non_uuid", "$session_id IN ('a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'not-a-uuid')"),
            # SQL injection attempts — none of these are valid UUIDs, so the optimization is
            # skipped and values go through the normal parameterized query path (%(hogql_val_N)s)
            ("sqli_uuid_with_suffix", "$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890; DROP TABLE events'"),
            ("sqli_uuid_with_parens", "$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef123456789()'"),
            ("sqli_overlong_hex", "$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef12345678901'"),
            ("sqli_short_hex", "$session_id = 'a1b2c3d4-e5f6-7890-abcd-ef123456789'"),
            ("sqli_non_hex_chars", "$session_id = 'g1b2c3d4-e5f6-7890-abcd-ef1234567890'"),
            (
                "sqli_in_with_injection",
                "$session_id IN ('a1b2c3d4-e5f6-7890-abcd-ef1234567890', '1; DROP TABLE events')",
            ),
        ]
    )
    def test_session_id_uuid_optimization_skipped(self, _name, expr):
        result = self._expr(expr)
        self.assertNotIn("$session_id_uuid", result)


@snapshot_clickhouse_queries
class TestMaterializedColumnOptimization(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _expr(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
    ) -> str:
        node = parse_expr(query)
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="clickhouse", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="clickhouse",
            stack=[prepared_select_query],
        )

    def _test_materialized_column_comparison(
        self,
        input_expression: str,
        expected_query: str,
        expected_context_values: Mapping[str, Any] | None = None,
        optimization_mode: MaterializedColumnsOptimizationMode | None = None,
    ) -> None:
        context = HogQLContext(
            team_id=self.team.pk,
            modifiers=HogQLQueryModifiers(
                materializationMode=MaterializationMode.AUTO,
                materializedColumnsOptimizationMode=optimization_mode,
            ),
        )
        printed_expr = self._expr(input_expression, context)
        assert printed_expr == expected_query

        if expected_context_values is not None:
            self.assertLessEqual(expected_context_values.items(), context.values.items())

    def test_materialized_column_optimized_equality_comparison_non_nullable(self) -> None:
        # Non-nullable columns don't need any wrapping
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop = 'some_value'",
                f"equals(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "some_value"},
            )
            self._test_materialized_column_comparison(
                "'some_value' = properties.test_prop",
                f"equals(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "some_value"},
            )
            self._test_materialized_column_comparison(
                "properties.test_prop != 'some_value'",
                f"notEquals(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "some_value"},
            )
            self._test_materialized_column_comparison(
                "'some_value' != properties.test_prop",
                f"notEquals(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "some_value"},
            )

    def test_materialized_column_optimized_equality_comparison_nullable(self) -> None:
        # Nullable columns need wrapping to handle NULL properly
        with materialized("events", "test_prop", is_nullable=True) as mat_col:
            # equals: use AND IS NOT NULL to preserve skip index usage
            self._test_materialized_column_comparison(
                "properties.test_prop = 'some_value'",
                f"(equals(events.{mat_col.name}, %(hogql_val_0)s) AND (events.{mat_col.name} IS NOT NULL))",
                {"hogql_val_0": "some_value"},
            )
            self._test_materialized_column_comparison(
                "'some_value' = properties.test_prop",
                f"(equals(events.{mat_col.name}, %(hogql_val_0)s) AND (events.{mat_col.name} IS NOT NULL))",
                {"hogql_val_0": "some_value"},
            )
            # notEquals: use ifNull since skip index is less important here
            self._test_materialized_column_comparison(
                "properties.test_prop != 'some_value'",
                f"ifNull(notEquals(events.{mat_col.name}, %(hogql_val_0)s), 1)",
                {"hogql_val_0": "some_value"},
            )
            self._test_materialized_column_comparison(
                "'some_value' != properties.test_prop",
                f"ifNull(notEquals(events.{mat_col.name}, %(hogql_val_0)s), 1)",
                {"hogql_val_0": "some_value"},
            )

    def test_materialized_column_equality_not_optimized_for_empty_string(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop = ''",
                f"ifNull(equals(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_0)s), 0)",
            )

    def test_materialized_column_equality_not_optimized_for_null_string(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop = 'null'",
                f"ifNull(equals(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_0)s), 0)",
            )

    def test_materialized_column_equality_not_optimized_for_non_string_constant(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop = 123",
                f"ifNull(equals(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), 123), 0)",
            )

    def test_materialized_column_equality_not_optimized_for_null_comparison(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop = null",
                f"isNull(nullIf(nullIf(events.{mat_col.name}, ''), 'null'))",
            )

    @parameterized.expand(
        [
            ("nullable", True),
            ("not nullable", False),
        ]
    )
    def test_materialized_column_optimization_returns_correct_results(self, _, is_nullable) -> None:
        with materialized("events", "test_prop", create_minmax_index=True, is_nullable=is_nullable) as mat_col:
            _create_event(
                team=self.team,
                distinct_id="d1",
                event="test_event",
                properties={"test_prop": "target_value"},
            )
            _create_event(
                team=self.team,
                distinct_id="d2",
                event="test_event",
                properties={"test_prop": "other_value"},
            )
            _create_event(
                team=self.team,
                distinct_id="d3",
                event="test_event",
                properties={"test_prop": ""},
            )
            _create_event(
                team=self.team,
                distinct_id="d4",
                event="test_event",
                properties={"test_prop": "null"},
            )
            _create_event(
                team=self.team,
                distinct_id="d5",
                event="test_event",
                properties={},
            )
            _create_event(
                team=self.team,
                distinct_id="d6",
                event="test_event",
                properties={"test_prop": None},
            )

            eq_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE properties.test_prop = 'target_value' ORDER BY distinct_id",
            )
            self.assertEqual(eq_result.results, [("d1",)])
            assert eq_result.clickhouse is not None
            index_name = get_minmax_index_name(mat_col.name)
            assert get_index_from_explain(eq_result.clickhouse, index_name), (
                f"Expected skip index {index_name} to be used"
            )

            neq_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE properties.test_prop != 'target_value' ORDER BY distinct_id",
            )
            self.assertEqual(neq_result.results, [("d2",), ("d3",), ("d4",), ("d5",), ("d6",)])

    @parameterized.expand(
        [
            ("materialized_joined", True, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            ("materialized_on_events", True, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("not_materialized_joined", False, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            ("not_materialized_on_events", False, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        ]
    )
    def test_person_property_is_not_set_behavior(
        self, _name: str, is_materialized: bool, poe_mode: PersonsOnEventsMode
    ):
        """
        Test that is_not_set behaves consistently across materialized/non-materialized columns
        and different PersonsOnEventsMode settings.

        Expected behavior:
        - with_email: is_not_set=0 - property has a value
        - test_with_empty_string: is_not_set=0 - property has a value
        - with_null: is_not_set=1 - null is treated as "not set"
        - without: is_not_set=1 - property doesn't exist

        the clickhouse SQL should NOT include JSON operations
        """
        self.addCleanup(cleanup_materialized_columns)

        if is_materialized:
            materialize("events", "email", table_column="person_properties")
            materialize("person", "email")

        # Generate unique IDs to avoid collision with previous test runs
        distinct_id_with_email = f"test_with_email"
        distinct_id_with_empty = f"test_with_empty_string"
        distinct_id_with_null = f"test_with_null"
        distinct_id_without = f"test_without"
        event_name = f"is_not_set_test"

        # Create four persons with different email property states:
        # 1. email set to a real value
        _create_person(
            distinct_ids=[distinct_id_with_email],
            team=self.team,
            properties={"email": "test@example.com"},
            immediate=True,
        )
        # 2. email set to empty string
        _create_person(
            distinct_ids=[distinct_id_with_empty],
            team=self.team,
            properties={"email": ""},
            immediate=True,
        )
        # 3. email set to null
        _create_person(
            distinct_ids=[distinct_id_with_null],
            team=self.team,
            properties={"email": None},
            immediate=True,
        )
        # 4. email not set at all
        _create_person(
            distinct_ids=[distinct_id_without],
            team=self.team,
            properties={},
            immediate=True,
        )

        # Create events for each person
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_email)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_empty)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_null)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_without)
        flush_persons_and_events()

        # Build the is_not_set expression using property_to_expr
        is_not_set_expr = property_to_expr(
            {"type": "person", "key": "email", "operator": "is_not_set"},
            team=self.team,
            scope="event",
        )

        # Build the full query AST
        query_ast = ast.SelectQuery(
            select=[
                ast.Alias(alias="distinct_id", expr=ast.Field(chain=["distinct_id"])),
                ast.Alias(alias="email_value", expr=ast.Field(chain=["person", "properties", "email"])),
                ast.Alias(alias="is_not_set_result", expr=is_not_set_expr),
                ast.Alias(
                    alias="is_not_set_result_historical",
                    expr=ast.Or(
                        exprs=[
                            is_not_set_expr,
                            ast.Not(
                                expr=ast.Call(
                                    name="JSONHas",
                                    args=[ast.Field(chain=["person", "properties"]), ast.Constant(value="email")],
                                )
                            ),
                        ]
                    ),
                ),  # this is the historical behaviour for is_not_set, was removed in https://github.com/PostHog/posthog/pull/44346 but test for equivalence here
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event_name),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["distinct_id"]))],
        )

        result = execute_hogql_query(
            team=self.team,
            query=query_ast,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=poe_mode),
        )
        assert result.clickhouse

        # Note: When columns are materialized, empty strings become NULL due to nullIf(nullIf(..., ''), 'null') wrapping - this is known inconsistent behaviour for materialized properties
        expected_results = {
            (distinct_id_with_email, "test@example.com", 0, 0),
            # Empty string behavior differs: becomes null when materialized
            (
                distinct_id_with_empty,
                None if is_materialized else "",
                1 if is_materialized else 0,
                1 if is_materialized else 0,
            ),
            (distinct_id_with_null, None, 1, 1),
            (distinct_id_without, None, 1, 1),
        }
        self.assertEqual(set(result.results), expected_results)

        # The query should never touch the json properties object if we are using the materialized column, these asserts protect against regression of the performance the bug fixed in
        # https://posthog.slack.com/archives/C09B0SSQEDA/p1767698123669229?thread_ts=1767672165.250289&cid=C09B0SSQEDA
        sql_lower = result.clickhouse.lower()
        # JSONHas is used in calculating is_not_set_result_historical, but nowhere else
        assert sql_lower.count("jsonhas") == 1
        if is_materialized:
            # the materialized version should not use any JSON operation, or any other Has operation (e.g. the Array/Set function `has`)
            assert sql_lower.count("json") == 1
            assert sql_lower.count("has") == 1
            assert sql_lower.count("contains") == 0

    def test_materialized_column_ilike_uses_raw_column_for_non_nullable(self) -> None:
        # For non-nullable columns, ILIKE uses raw column directly
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop ilike '%@posthog.com%'",
                f"ilike(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%@posthog.com%"},
            )
            # should also work if wrapped with toString()
            self._test_materialized_column_comparison(
                "ilike(toString(properties.test_prop), '%@gmail.com%')",
                f"ilike(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%@gmail.com%"},
            )

    def test_materialized_column_ilike_with_tostring_uses_ngram_index_for_non_nullable(self) -> None:
        # toString() wrapper should use ngram index optimization when available
        with materialized("events", "test_prop", is_nullable=False, create_ngram_lower_index=True) as mat_col:
            self._test_materialized_column_comparison(
                "ilike(properties.test_prop, '%@gmail.com%')",
                f"like(lower(events.{mat_col.name}), lower(%(hogql_val_0)s))",
                {"hogql_val_0": "%@gmail.com%"},
            )

            # should also work if wrapped with toString()
            self._test_materialized_column_comparison(
                "ilike(toString(properties.test_prop), '%@gmail.com%')",
                f"like(lower(events.{mat_col.name}), lower(%(hogql_val_0)s))",
                {"hogql_val_0": "%@gmail.com%"},
            )

            self._test_materialized_column_comparison(
                "ilike(JSONExtractString(properties, 'test_prop'), '%@gmail.com%')",
                f"like(lower(events.{mat_col.name}), lower(%(hogql_val_0)s))",
                {"hogql_val_0": "%@gmail.com%"},
            )

    def test_materialized_column_ilike_with_tostring_not_optimized_for_numeric_property(self) -> None:
        # Numeric properties should not use the ILIKE optimization - fall back to default handling
        PropertyDefinition.objects.create(
            team=self.team,
            project=self.team.project,
            name="test_numeric_prop",
            property_type="Numeric",
            type=PropertyDefinition.Type.EVENT,
        )
        with materialized("events", "test_numeric_prop", is_nullable=False) as mat_col:
            # Direct property access: optimization skipped, PropertySwapper wraps in accurateCastOrNull
            self._test_materialized_column_comparison(
                "ilike(properties.test_numeric_prop, '%123%')",
                f"ifNull(ilike(accurateCastOrNull(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_0)s), %(hogql_val_1)s), 0)",
                {"hogql_val_1": "%123%"},
            )

            # With toString() wrapper: same behavior, optimization not applied
            self._test_materialized_column_comparison(
                "ilike(toString(properties.test_numeric_prop), '%123%')",
                f"ifNull(ilike(toString(accurateCastOrNull(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_0)s)), %(hogql_val_1)s), 0)",
                {"hogql_val_1": "%123%"},
            )

    def test_materialized_column_not_ilike_uses_raw_column_for_non_nullable(self) -> None:
        # For non-nullable columns, NOT ILIKE uses raw column directly
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop not ilike '%@posthog.com%'",
                f"notILike(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%@posthog.com%"},
            )

    def test_materialized_column_ilike_bails_out_for_sentinel_pattern_on_non_nullable(self) -> None:
        # For non-nullable columns, patterns that could match sentinel values bail out
        # of the optimization and let the normal code path handle it with proper nullif wrapping
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop ilike '%null%'",
                f"ifNull(ilike(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_1)s), 0)",
                {"hogql_val_1": "%null%"},
            )
            self._test_materialized_column_comparison(
                "properties.test_prop ilike '%NULL%'",
                f"ifNull(ilike(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_1)s), 0)",
                {"hogql_val_1": "%NULL%"},
            )

    def test_materialized_column_like_uses_raw_column_for_non_nullable(self) -> None:
        # For non-nullable columns, LIKE uses raw column directly
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop like '%@posthog.com%'",
                f"like(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%@posthog.com%"},
            )

    def test_materialized_column_not_like_uses_raw_column_for_non_nullable(self) -> None:
        # For non-nullable columns, NOT LIKE uses raw column directly
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop not like '%@posthog.com%'",
                f"notLike(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%@posthog.com%"},
            )

    def test_materialized_column_like_case_sensitivity(self) -> None:
        # LIKE is case-sensitive, so %NULL% doesn't match lowercase "null" sentinel
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop like '%NULL%'",
                f"like(events.{mat_col.name}, %(hogql_val_0)s)",
                {"hogql_val_0": "%NULL%"},
            )

    def test_materialized_column_like_bails_out_for_sentinel_pattern_on_non_nullable(self) -> None:
        # For non-nullable columns, %null% bails out of optimization
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop like '%null%'",
                f"ifNull(like(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), %(hogql_val_0)s), 0)",
                {"hogql_val_0": "%null%"},
            )

    def test_materialized_column_in_uses_raw_column_for_non_nullable(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop in ('value1', 'value2')",
                f"has([%(hogql_val_0)s, %(hogql_val_1)s], events.{mat_col.name})",
                {"hogql_val_0": "value1", "hogql_val_1": "value2"},
            )

    def test_materialized_column_not_in_uses_raw_column_for_non_nullable(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop not in ('value1', 'value2')",
                f"notIn(events.{mat_col.name}, tuple(%(hogql_val_0)s, %(hogql_val_1)s))",
                {"hogql_val_0": "value1", "hogql_val_1": "value2"},
            )

    def test_materialized_column_in_bails_out_for_sentinel_value_on_non_nullable(self) -> None:
        # When sentinel values are present, we bail out and let default handling apply nullIf wrapping
        # Note: default IN handling does not add ifNull wrapper (unlike Eq/Like)
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop in ('null', 'value2')",
                f"in(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), tuple(%(hogql_val_0)s, %(hogql_val_1)s))",
                {"hogql_val_0": "null", "hogql_val_1": "value2"},
            )
            self._test_materialized_column_comparison(
                "properties.test_prop in ('', 'value2')",
                f"in(nullIf(nullIf(events.{mat_col.name}, ''), 'null'), tuple(%(hogql_val_0)s, %(hogql_val_1)s))",
                {"hogql_val_0": "", "hogql_val_1": "value2"},
            )

    def test_materialized_column_in_nullable(self) -> None:
        with materialized("events", "test_prop", is_nullable=True) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop in ('value1', 'value2')",
                f"and(has([%(hogql_val_0)s, %(hogql_val_1)s], events.{mat_col.name}), events.mat_test_prop IS NOT NULL)",
                {"hogql_val_0": "value1", "hogql_val_1": "value2"},
            )

    def test_materialized_column_not_in_nullable(self) -> None:
        with materialized("events", "test_prop", is_nullable=True) as mat_col:
            self._test_materialized_column_comparison(
                "properties.test_prop not in ('value1', 'value2')",
                f"ifNull(notIn(events.{mat_col.name}, tuple(%(hogql_val_0)s, %(hogql_val_1)s)), 1)",
                {"hogql_val_0": "value1", "hogql_val_1": "value2"},
            )

    def test_force_data_skipping_indices_works_with_simple_equality(self) -> None:
        with materialized("events", "test_prop", is_nullable=False, create_bloom_filter_index=True) as mat_col:
            _create_event(team=self.team, distinct_id="test", event="test", properties={"test_prop": "foo"})

            index_name = get_bloom_filter_index_name(mat_col.name)
            result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE properties.test_prop = 'foo'",
                modifiers=HogQLQueryModifiers(
                    materializationMode=MaterializationMode.AUTO,
                    forceClickhouseDataSkippingIndexes=[index_name],
                ),
            )

            assert result.results == [("test",)]
            assert result.clickhouse
            assert f"force_data_skipping_indices='{index_name}'" in result.clickhouse

    def test_force_data_skipping_indices_fails_when_index_cannot_be_used(self) -> None:
        with materialized("events", "test_prop", is_nullable=False, create_bloom_filter_index=True) as mat_col:
            _create_event(team=self.team, distinct_id="test", event="test", properties={"test_prop": "foo"})

            index_name = get_bloom_filter_index_name(mat_col.name)
            with pytest.raises(Exception) as exc_info:
                execute_hogql_query(
                    team=self.team,
                    query="SELECT distinct_id FROM events WHERE concat(properties.test_prop, '') = 'foo'",
                    modifiers=HogQLQueryModifiers(
                        materializationMode=MaterializationMode.AUTO,
                        forceClickhouseDataSkippingIndexes=[index_name],
                    ),
                )

            assert "index" in str(exc_info.value).lower()

    @parameterized.expand(
        [
            ("no_mat_col", None, False),
            ("nullable_mat_col", True, False),
            ("non_nullable_mat_col", False, False),
            ("nullable_mat_col_with_ngram_lower", True, True),
            ("non_nullable_mat_col_with_ngram_lower", False, True),
        ]
    )
    def test_ilike_and_not_ilike_optimization_gives_correct_results(
        self, _, is_nullable, create_ngram_lower_index
    ) -> None:
        if is_nullable is not None:
            mat_col = materialize(
                "events", "test_prop", is_nullable=is_nullable, create_ngram_lower_index=create_ngram_lower_index
            )
            self.addCleanup(cleanup_materialized_columns)
        else:
            mat_col = None

        # do multiple test cases per test run, as setup and teardown are a bit slow
        cases: set[str] = {
            "hello@posthog.com",
            "Hello@PostHog.com",
            "other_value",
            "null",
            "NULL",
            "'null'",
            "contains null in the middle",
            "null@posthog.com",
            "",
            "None",  # Store None (i.e. actual NULL value) as a string, because we can't have a NULL distinct_id and it makes things easier
        }

        # Map of patterns to (ilike_expected, ilike_expected_if_non_nullable) - can use ilike_expected_if_non_nullable=None to fall back to ilike_expected.
        # Note that non-nullable mat columns treat the '' and 'null' values as NULL, this is a bug/"feature" in non-nullable mat columns, not in our optimization.
        # In this case we bail out of our optimization and fall back to default NULL handling/wrapping.
        # It'd be a good thing to fix this! And remove these special-cases from the tests! but my top priority was making sure that I didn't change any behavior.
        patterns_and_expected = {
            "%@posthog.com": ({"hello@posthog.com", "Hello@PostHog.com", "null@posthog.com"}, None),
            "hello@posthog.com": ({"hello@posthog.com", "Hello@PostHog.com"}, None),
            "%null%": (
                {"null", "NULL", "'null'", "null@posthog.com", "contains null in the middle"},
                {"NULL", "'null'", "null@posthog.com", "contains null in the middle"},
            ),
            "%": (
                {
                    "",
                    "hello@posthog.com",
                    "Hello@PostHog.com",
                    "other_value",
                    "null",
                    "NULL",
                    "'null'",
                    "contains null in the middle",
                    "null@posthog.com",
                },
                {
                    "hello@posthog.com",
                    "Hello@PostHog.com",
                    "other_value",
                    "NULL",
                    "'null'",
                    "contains null in the middle",
                    "null@posthog.com",
                },
            ),
            "": ({""}, set()),
            "None": ({"None"}, {"None", "", "null"}),
        }

        for case in cases:
            _create_event(
                team=self.team,
                distinct_id=case,
                event="test_event",
                properties={"test_prop": case if case != "None" else None},
            )
        flush_persons_and_events()

        for pattern, (ilike_expected, ilike_expected_if_non_nullable) in patterns_and_expected.items():
            if ilike_expected_if_non_nullable is not None and (is_nullable is False):
                ilike_expected = ilike_expected_if_non_nullable
            pattern_expr = ast.Constant(value=pattern if pattern != "None" else None)
            ilike_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE ilike(properties.test_prop, {pattern}) ORDER BY distinct_id",
                placeholders={"pattern": pattern_expr},
            )
            ilike_matches = {d for (d,) in ilike_result.results}
            assert ilike_matches == ilike_expected, "ilike " + str(pattern)

            if mat_col:
                assert ilike_result.clickhouse
                # we can only ever use the index if it exists, pattern was not NULL, and we didn't need to bail out of the optimisation
                should_use_index = (
                    create_ngram_lower_index
                    and pattern != "None"
                    and (is_nullable or (ilike_expected_if_non_nullable is None))
                )
                did_use_index = bool(
                    get_index_from_explain(ilike_result.clickhouse, get_ngram_lower_index_name(mat_col.name))
                )
                assert should_use_index == did_use_index

            not_ilike_expected = cases.difference(ilike_expected)
            not_ilike_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE notILike(properties.test_prop, {pattern}) ORDER BY distinct_id",
                placeholders={"pattern": pattern_expr},
            )
            not_ilike_matches = {d for (d,) in not_ilike_result.results}
            assert not_ilike_matches == not_ilike_expected, "not_ilike " + str(pattern)

    @parameterized.expand(
        [
            ("no_mat_col", None, False),
            ("nullable_mat_col", True, False),
            ("non_nullable_mat_col", False, False),
            ("nullable_mat_col_with_bloom_filter", True, True),
            ("non_nullable_mat_col_with_bloom_filter", False, True),
        ]
    )
    def test_in_and_not_in_optimization_gives_correct_results(self, _, is_nullable, create_bloom_filter_index) -> None:
        if is_nullable is not None:
            mat_col = materialize(
                "events", "test_prop", is_nullable=is_nullable, create_bloom_filter_index=create_bloom_filter_index
            )
            self.addCleanup(cleanup_materialized_columns)
        else:
            mat_col = None

        cases: set[str] = {
            "hello@posthog.com",
            "Hello@PostHog.com",
            "other_value",
            "null",
            "NULL",
            "'null'",
            "contains null in the middle",
            "null@posthog.com",
            "",
            "None",
        }

        # Map of IN values to (in_expected, in_expected_if_non_nullable). If in_expected_if_non_nullable is None, use in_expected.
        # Non-nullable mat columns treat '' and 'null' values as NULL.
        in_values_and_expected: dict[tuple[str, ...], tuple[set[str], set[str] | None]] = {
            ("hello@posthog.com",): ({"hello@posthog.com"}, None),
            ("hello@posthog.com", "other_value"): ({"hello@posthog.com", "other_value"}, None),
            ("null",): ({"null"}, set()),
            ("NULL",): ({"NULL"}, None),
            ("null", "NULL"): ({"null", "NULL"}, {"NULL"}),
            ("",): ({""}, set()),
            ("hello@posthog.com", "null"): ({"hello@posthog.com", "null"}, {"hello@posthog.com"}),
            ("hello@posthog.com", ""): ({"hello@posthog.com", ""}, {"hello@posthog.com"}),
        }

        for case in cases:
            _create_event(
                team=self.team,
                distinct_id=case,
                event="test_event",
                properties={"test_prop": case if case != "None" else None},
            )

        for in_values, (in_expected, in_expected_if_non_nullable) in in_values_and_expected.items():
            if in_expected_if_non_nullable is not None and (is_nullable is False):
                in_expected = in_expected_if_non_nullable

            in_values_exprs: list[ast.Expr] = [ast.Constant(value=v) for v in in_values]
            in_tuple = ast.Tuple(exprs=in_values_exprs)

            in_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE properties.test_prop IN {in_values} ORDER BY distinct_id",
                placeholders={"in_values": in_tuple},
            )
            in_matches = {d for (d,) in in_result.results}
            assert in_matches == in_expected, f"IN {in_values}"

            if mat_col:
                assert in_result.clickhouse
                # We can use the bloom filter index if it exists and we didn't need to bail out of the optimisation
                contains_sentinel = any(v in ("", "null") for v in in_values)
                should_use_index = create_bloom_filter_index and (is_nullable or not contains_sentinel)
                index_name = get_bloom_filter_index_name(mat_col.name)
                index_info = get_index_from_explain(in_result.clickhouse, index_name)
                did_use_index = bool(index_info)
                assert should_use_index == did_use_index, f"IN {in_values}: expected index use={should_use_index}"

            not_in_expected = cases.difference(in_expected)
            not_in_result = execute_hogql_query(
                team=self.team,
                query="SELECT distinct_id FROM events WHERE properties.test_prop NOT IN {in_values} ORDER BY distinct_id",
                placeholders={"in_values": in_tuple},
            )
            not_in_matches = {d for (d,) in not_in_result.results}
            assert not_in_matches == not_in_expected, f"NOT IN {in_values}"

    def test_recursive_cte_raises(self):
        query = """
        WITH RECURSIVE cte AS (
            SELECT 1 AS n
            UNION ALL
            SELECT n + 1 FROM cte WHERE n < 5
        )
        SELECT * FROM cte;
        """
        with self.assertRaises(ImpossibleASTError):
            execute_hogql_query(team=self.team, query=query)

    def test_jsonextractstring_rewrite_emits_mat_column(self) -> None:
        with materialized("events", "test_prop", is_nullable=False) as mat_col:
            printed = self._expr("JSONExtractString(properties, 'test_prop')")
            assert printed == f"nullIf(nullIf(events.{mat_col.name}, ''), 'null')"


class TestSessionIdUuidOptimization(ClickhouseTestMixin, APIBaseTest):
    SESSION_UUID_1 = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    SESSION_UUID_2 = "b2c3d4e5-f6a7-8901-bcde-f12345678901"

    def setUp(self):
        super().setUp()
        _create_person(distinct_ids=["user1"], team_id=self.team.pk)
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user1",
            properties={"$session_id": self.SESSION_UUID_1, "color": "blue"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user1",
            properties={"$session_id": self.SESSION_UUID_2, "color": "red"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user1",
            properties={"$session_id": "not-a-uuid", "color": "green"},
        )

    @parameterized.expand(
        [
            (
                "eq_direct_field",
                "SELECT properties.color FROM events WHERE $session_id = '{session_uuid_1}' ORDER BY properties.color",
                [("blue",)],
            ),
            (
                "eq_property_access",
                "SELECT properties.color FROM events WHERE properties.$session_id = '{session_uuid_1}' ORDER BY properties.color",
                [("blue",)],
            ),
            (
                "neq_direct_field",
                "SELECT properties.color FROM events WHERE $session_id != '{session_uuid_1}' AND $session_id = '{session_uuid_2}' ORDER BY properties.color",
                [("red",)],
            ),
            (
                "in_operation",
                "SELECT properties.color FROM events WHERE $session_id IN ('{session_uuid_1}', '{session_uuid_2}') ORDER BY properties.color",
                [("blue",), ("red",)],
            ),
            (
                "not_in_operation",
                "SELECT properties.color FROM events WHERE $session_id NOT IN ('{session_uuid_1}') AND $session_id = '{session_uuid_2}' ORDER BY properties.color",
                [("red",)],
            ),
        ]
    )
    def test_session_id_uuid_query(self, _name, query_template, expected):
        query = query_template.format(session_uuid_1=self.SESSION_UUID_1, session_uuid_2=self.SESSION_UUID_2)
        response = execute_hogql_query(team=self.team, query=query)
        self.assertEqual(response.results, expected)

    # Remove xfail when we add a minmax index on $session_id_uuid (see events table in posthog/models/event/sql.py)
    # see https://posthog.slack.com/archives/C076R4753Q8/p1772027599338529
    @pytest.mark.xfail(strict=True, reason="No minmax index on $session_id_uuid yet")
    def test_session_id_uuid_uses_minmax_index(self):
        query = f"SELECT properties.color FROM events WHERE $session_id = '{self.SESSION_UUID_1}'"
        response = execute_hogql_query(team=self.team, query=query)
        assert response.clickhouse is not None
        index_info = get_index_from_explain(response.clickhouse, "minmax_$session_id_uuid")
        assert index_info, "Expected minmax_$session_id_uuid skip index to be used"


class TestPrinted(APIBaseTest):
    def test_can_call_parametric_function(self):
        query = parse_select("SELECT arrayReduce('sum', [1, 2, 3])")
        query_response = execute_hogql_query(
            team=self.team,
            query=query,
        )
        assert query_response.results == [(6,)]


class TestPostgresPrinter(BaseTest):
    maxDiff = None

    def _expr(
        self,
        query: ast.Expr | str,
        context: Optional[HogQLContext] = None,
        settings: Optional[HogQLQuerySettings] = None,
        backend: HogQLParserBackend = "cpp-json",
    ) -> str:
        node = parse_expr(query, backend=backend) if isinstance(query, str) else query
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(
            select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])), settings=settings
        )
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="postgres", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="postgres",
            stack=[prepared_select_query],
        )

    def _select(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        placeholders: Optional[dict[str, ast.Expr]] = None,
        dialect: HogQLDialect = "postgres",
    ) -> str:
        return prepare_and_print_ast(
            parse_select(query, placeholders=placeholders, backend="cpp-json"),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect,
        )[0]

    @parameterized.expand(
        [
            ("is_null", "event is null", "(events.event IS NULL)"),
            ("is_not_null", "event is not null", "(events.event IS NOT NULL)"),
            ("eq_null", "event = null", "(events.event = NULL)"),
            ("neq_null", "event != null", "(events.event != NULL)"),
        ]
    )
    def test_null_comparisons_in_postgres(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            (
                "SELECT event FROM events",
                "SELECT events.event FROM events LIMIT 50000",
            ),
            (
                "SELECT distinct_id, event FROM events WHERE event = 'test'",
                "SELECT events.distinct_id, events.event FROM events WHERE (events.event = %(hogql_val_0)s) LIMIT 50000",
            ),
            (
                "SELECT event FROM events ORDER BY timestamp DESC",
                "SELECT events.event FROM events ORDER BY events.timestamp DESC LIMIT 50000",
            ),
            (
                "SELECT #1, #2 FROM events",
                "SELECT #1, #2 FROM events LIMIT 50000",
            ),
            (
                "SELECT count() FROM events GROUP BY event",
                "SELECT count() FROM events GROUP BY events.event LIMIT 50000",
            ),
        ]
    )
    def test_select_queries(self, query: str, expected: str):
        self.assertEqual(self._select(query), expected)

    def test_omits_clickhouse_specific_transforms(self):
        postgres = self._select("SELECT event FROM events")
        clickhouse = self._select("SELECT event FROM events", dialect="clickhouse")

        self.assertNotIn("team_id", postgres)
        self.assertNotEqual(postgres, clickhouse)

    def test_column_aliases(self):
        printed = self._select("SELECT 1 FROM events AS e (event_alias, ts_alias)")
        self.assertIn("AS e (event_alias, ts_alias)", printed)

    def test_column_aliases_explicit_refs_use_aliased_names(self):
        printed = self._select("SELECT e.a, e.b FROM events AS e (a, b, c)")
        # Postgres supports (a, b, c) syntax natively, so field references
        # should use the aliased names
        self.assertIn("e.a", printed)
        self.assertIn("e.b", printed)
        self.assertNotIn("e.uuid", printed)
        self.assertNotIn("e.event", printed)

    def test_column_aliases_in_where(self):
        printed = self._select("SELECT e.a FROM events AS e (a, b, c) WHERE e.c IS NOT NULL")
        self.assertIn("e.a", printed)
        self.assertIn("e.c", printed)

    def test_column_aliases_select_star(self):
        printed = self._select("SELECT s.* FROM (SELECT 1 AS x, 2 AS y, 3 AS z) AS s (a, b, c)")
        self.assertIn("s.a", printed)
        self.assertIn("s.b", printed)
        self.assertIn("s.c", printed)

    def test_column_aliases_subquery_preserves_syntax(self):
        printed = self._select("SELECT s.a FROM (SELECT 1 AS x, 2 AS y) AS s (a, b)")
        self.assertIn("(a, b)", printed)
        self.assertIn("s.a", printed)

    @parameterized.expand(
        [
            ("range_one_arg", "SELECT range FROM range(10)", "range(10)"),
            ("range_two_args", "SELECT range FROM range(1, 10)", "range(1, 10)"),
            ("range_three_args", "SELECT range FROM range(0, 10, 2)", "range(0, 10, 2)"),
            (
                "generate_series_two_args",
                "SELECT generate_series FROM generate_series(1, 10)",
                "generate_series(1, 10)",
            ),
        ]
    )
    def test_range_table_function_prints(self, _name, query, expected):
        printed = self._select(query)
        self.assertIn(expected, printed)

    @parameterized.expand(
        [
            ("no_args", "SELECT range FROM range", "requires arguments"),
            ("empty_args", "SELECT range FROM range()", "requires at least 1 argument"),
            ("too_many_args", "SELECT range FROM range(1, 2, 3, 4)", "requires at most 3 arguments"),
        ]
    )
    def test_range_table_function_arg_errors(self, _name, query, expected_error):
        with self.assertRaises(QueryError) as ctx:
            self._select(query)
        self.assertIn(expected_error, str(ctx.exception))

    def _context_with_table_functions(self, *function_names: str) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            direct_postgres_connection_metadata={
                "available_table_functions": list(function_names),
            },
        )

    @parameterized.expand(
        [
            ("unnest", "SELECT unnest FROM unnest(ARRAY[1, 2, 3])", "unnest("),
            (
                "regexp_matches",
                "SELECT regexp_matches FROM regexp_matches('abc', '.', 'g')",
                "regexp_matches(",
            ),
            (
                "jsonb_array_elements_text",
                "SELECT jsonb_array_elements_text FROM jsonb_array_elements_text('[\"a\"]')",
                "jsonb_array_elements_text(",
            ),
        ]
    )
    def test_opaque_table_function_from_introspected_metadata(self, name, query, expected):
        context = self._context_with_table_functions(name)
        printed = self._select(query, context=context)
        self.assertIn(expected, printed)

    def test_opaque_table_function_unknown_name_still_errors(self):
        context = self._context_with_table_functions("unnest")
        with self.assertRaises(QueryError) as ctx:
            self._select("SELECT * FROM totally_made_up_function(1)", context=context)
        self.assertIn("Unknown table", str(ctx.exception))

    def test_opaque_table_function_requires_args(self):
        context = self._context_with_table_functions("unnest")
        with self.assertRaises(QueryError) as ctx:
            self._select("SELECT * FROM unnest", context=context)
        self.assertIn("Unknown table", str(ctx.exception))

    def test_opaque_table_function_rejects_empty_call(self):
        context = self._context_with_table_functions("unnest")
        with self.assertRaises(QueryError) as ctx:
            self._select("SELECT * FROM unnest()", context=context)
        self.assertIn("requires at least 1 argument", str(ctx.exception))

    def test_opaque_table_function_falls_back_to_hardcoded_range_without_metadata(self):
        # Connections that haven't refreshed since this rolled out won't have
        # `available_table_functions` in their metadata. The hand-rolled RangeTable
        # / GenerateSeriesTable registrations keep those two working.
        printed = self._select("SELECT range FROM range(10)")
        self.assertIn("range(10)", printed)

    @parameterized.expand(
        [
            (
                "basic",
                "SELECT 1 FROM events PIVOT (count() FOR event IN ('a', 'b'))",
                "SELECT 1 FROM events PIVOT (count() FOR events.event IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000",
            ),
            (
                "multiple_columns",
                "SELECT 1 FROM events PIVOT (count() FOR event IN ('a') distinct_id IN (1, 2) GROUP BY timestamp)",
                "SELECT 1 FROM events PIVOT (count() FOR events.event IN (%(hogql_val_0)s) events.distinct_id IN (1, 2) GROUP BY events.timestamp) LIMIT 50000",
            ),
            (
                "join",
                "SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN ('a'))",
                "SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN (%(hogql_val_0)s)) LIMIT 50000",
            ),
        ]
    )
    def test_pivot_prints(self, _name: str, query: str, expected: str):
        self.assertEqual(self._select(query), expected)

    def test_limit_percent_basic(self):
        printed = self._select("SELECT 1 FROM events LIMIT 10 %")
        self.assertIn("LIMIT 10 %", printed)

    def test_limit_percent_expr(self):
        printed = self._select("SELECT 1 FROM events LIMIT (60 + 7) %")
        self.assertIn("LIMIT (60 + 7) %", printed)

    def test_lambda_style(self):
        printed = self._select("SELECT lambda x, y: x + y")
        self.assertIn("lambda x, y: (x + y)", printed)

    @parameterized.expand(
        [
            ("[1, 2, 3][1:2]", "[1, 2, 3][1:2]"),
            ("[1, 2, 3][:]", "[1, 2, 3][:]"),
            ("[1, 2, 3][(1 + 2):(-3)]", "[1, 2, 3][(1 + 2):-3]"),
            ("[1, 2, 3][-5:]", "[1, 2, 3][-5:]"),
            ("([1, 2, 3] || [4, 5, 6])[1:3]", "concat([1, 2, 3], [4, 5, 6])[1:3]"),
        ]
    )
    def test_array_slice(self, expr: str, expected: str):
        printed = self._select(f"SELECT {expr}")
        self.assertIn(expected, printed)

    @parameterized.expand(
        [
            ("try_cast(1 AS Int64)", "TRY_CAST(1 AS int64)"),
            ("try_cast(1 AS Int64) + 1", "TRY_CAST(1 AS int64)"),
        ]
    )
    def test_try_cast(self, expr: str, expected: str):
        printed = self._select(f"SELECT {expr}")
        self.assertIn(expected, printed)

    @parameterized.expand(
        [
            (
                "sum_desc",
                "SELECT sum(event ORDER BY timestamp DESC) FROM events",
                "SELECT sum(events.event ORDER BY events.timestamp DESC) FROM events LIMIT 50000",
            ),
        ]
    )
    def test_function_call_order_by_prints(self, _name: str, query: str, expected: str):
        self.assertEqual(self._select(query), expected)

    @parameterized.expand(
        [
            ("1 IS DISTINCT FROM 2", "1 IS DISTINCT FROM 2"),
            ("1 IS NOT DISTINCT FROM 2", "1 IS NOT DISTINCT FROM 2"),
        ]
    )
    def test_is_distinct_from(self, expr: str, expected: str):
        printed = self._select(f"SELECT {expr}")
        self.assertIn(expected, printed)

    @parameterized.expand(
        [
            (
                "is_distinct_from_alias_rhs",
                ast.IsDistinctFrom(
                    left=ast.Constant(value=""),
                    right=ast.Alias(alias="x", expr=ast.Constant(value=True)),
                ),
            ),
            (
                "is_not_distinct_from_alias_lhs",
                ast.IsDistinctFrom(
                    left=ast.Alias(alias="x", expr=ast.Field(chain=["a"])),
                    right=ast.Constant(value=1),
                    negated=True,
                ),
            ),
            (
                "between_alias_expr",
                ast.BetweenExpr(
                    expr=ast.Alias(alias="x", expr=ast.Field(chain=["a"])),
                    low=ast.Constant(value=1),
                    high=ast.Constant(value=10),
                ),
            ),
            (
                "between_alias_bounds",
                ast.BetweenExpr(
                    expr=ast.Constant(value=5),
                    low=ast.Alias(alias="lo", expr=ast.Constant(value=1)),
                    high=ast.Alias(alias="hi", expr=ast.Constant(value=10)),
                ),
            ),
        ]
    )
    def test_alias_in_infix_operator_roundtrips(self, _name: str, node: ast.Expr):
        """Regression: aliases inside BETWEEN / IS DISTINCT FROM must be parenthesized
        by the printer so the HogQL roundtrip is stable, and the parsed AST has the
        same top-level node type as the original."""
        printed = node.to_hogql()
        parsed = parse_expr(printed)
        self.assertEqual(type(parsed), type(node), f"AST type changed after roundtrip of: {printed!r}")
        reprinted = parsed.to_hogql()
        self.assertEqual(printed, reprinted)

    def test_limit_percent_with_subquery(self):
        printed = self._select("SELECT 1 FROM events LIMIT (SELECT avg(team_id) FROM events) %")
        self.assertIn("LIMIT (SELECT avg(events.team_id) FROM events) %", printed)

    def test_limit_percent_with_offset(self):
        printed = self._select("SELECT 1 FROM events LIMIT 42% OFFSET 20")
        self.assertIn("LIMIT 42 % OFFSET 20", printed)

    def test_boolean_and_null_literals(self):
        self.assertEqual(self._expr("true"), "true")
        self.assertEqual(self._expr("false"), "false")
        self.assertEqual(self._expr("null"), "NULL")

    def test_json_properties_render_as_postgres_json_access(self):
        self.assertEqual(
            self._expr("properties.a.b.c.$browser"),
            "((((events.properties) -> 'a') -> 'b') -> 'c') ->> '$browser'",
        )

    def test_json_properties_in_select_render_as_postgres_json_access(self):
        printed = self._select("SELECT properties.detail.name FROM events")

        self.assertIn("(events.properties) ->", printed)
        self.assertIn("->> 'name'", printed)
        self.assertIn('AS "properties.detail.name"', printed)

    def test_allows_dollar_identifiers(self):
        printed = self._select("SELECT event AS $value FROM events")
        self.assertIn('AS "$value"', printed)

    def test_simple_identifiers_render_without_quotes(self):
        self.assertEqual(self._expr("count(id)"), "count(id)")

    @parameterized.expand(
        [
            ("toStartOfSecond(timestamp)", "date_trunc('second', events.timestamp)"),
            ("toStartOfMinute(timestamp)", "date_trunc('minute', events.timestamp)"),
            ("toStartOfHour(timestamp)", "date_trunc('hour', events.timestamp)"),
            ("toStartOfDay(timestamp)", "date_trunc('day', events.timestamp)"),
            ("toStartOfMonth(timestamp)", "date_trunc('month', events.timestamp)"),
            ("toStartOfQuarter(timestamp)", "date_trunc('quarter', events.timestamp)"),
            ("toStartOfYear(timestamp)", "date_trunc('year', events.timestamp)"),
            (
                "toStartOfISOYear(timestamp)",
                "date_trunc('week', make_date(extract(isoyear from events.timestamp)::int, 1, 4)::timestamp)",
            ),
        ]
    )
    def test_to_start_of_functions_render_as_date_trunc(self, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_to_start_of_week_defaults_to_sunday_in_postgres(self):
        self.assertEqual(
            self._expr("toStartOfWeek(timestamp)"),
            "(date_trunc('week', (events.timestamp + interval '1 day')) - interval '1 day')",
        )

    def test_to_start_of_week_uses_project_week_start_day_in_postgres(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=Database(week_start_day=WeekStartDay.MONDAY),
        )

        self.assertEqual(self._expr("toStartOfWeek(timestamp)", context), "date_trunc('week', events.timestamp)")

    @parameterized.expand(
        [
            (
                "toStartOfWeek(timestamp, 0)",
                "(date_trunc('week', (events.timestamp + interval '1 day')) - interval '1 day')",
            ),
            ("toStartOfWeek(timestamp, 3)", "date_trunc('week', events.timestamp)"),
        ]
    )
    def test_to_start_of_week_preserves_supported_modes_in_postgres(self, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_to_start_of_week_rejects_unsupported_mode_in_postgres(self):
        with self.assertRaises(QueryError) as error:
            self._expr("toStartOfWeek(timestamp, 2)")

        self.assertIn("Unsupported toStartOfWeek mode", str(error.exception))

    def test_to_start_of_day_rejects_timezone_override_in_postgres(self):
        with self.assertRaises(QueryError) as error:
            self._expr("toStartOfDay(timestamp, 'UTC')")

        self.assertIn("timezone override", str(error.exception))

    @parameterized.expand(
        [
            ("date_trunc('second', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('minute', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('hour', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('day', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('week', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('month', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('quarter', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
            ("date_trunc('year', timestamp)", "date_trunc(%(hogql_val_0)s, events.timestamp)"),
        ]
    )
    def test_date_trunc_passthrough_in_postgres(self, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            (
                "toStartOfFiveMinutes(timestamp)",
                "date_trunc('hour', events.timestamp) + "
                "(floor(extract(minute from events.timestamp) / 5)::int * 5 * interval '1 minute')",
            ),
            (
                "toStartOfTenMinutes(timestamp)",
                "date_trunc('hour', events.timestamp) + "
                "(floor(extract(minute from events.timestamp) / 10)::int * 10 * interval '1 minute')",
            ),
            (
                "toStartOfFifteenMinutes(timestamp)",
                "date_trunc('hour', events.timestamp) + "
                "(floor(extract(minute from events.timestamp) / 15)::int * 15 * interval '1 minute')",
            ),
        ]
    )
    def test_to_start_of_minute_bucket_functions_render_in_postgres(self, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_reserved_identifiers_are_quoted(self):
        printed = self._select("SELECT events.event AS select FROM events")

        self.assertIn('AS "select"', printed)

    def test_long_generated_identifier_is_truncated_for_postgres(self):
        long_alias = "posthog_user__posthog_organizationmemberships__organization___id"
        printed = self._select(f"SELECT event AS {long_alias} FROM events")

        self.assertIn("AS ", printed)
        self.assertNotIn(long_alias, printed)

    def test_window_functions_keep_postgres_shape(self):
        printed = self._select("SELECT lag(timestamp) OVER (ORDER BY timestamp) FROM events")

        self.assertIn("lag(", printed)
        self.assertNotIn("lagInFrame", printed)
        self.assertNotIn("ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING", printed)

    @parameterized.expand([["percentile_cont"], ["percentile_disc"]])
    def test_percentile_within_group_renders_in_postgres(self, function_name: str):
        self.assertEqual(
            self._expr(f"{function_name}(0.5) within group (order by timestamp desc)"),
            f"{function_name}(0.5) WITHIN GROUP (ORDER BY events.timestamp DESC)",
        )

    def test_in_operations_render_value_lists(self):
        self.assertEqual(self._expr("1 in (1, 2, 3)"), "(1 IN (1, 2, 3))")
        self.assertEqual(self._expr("1 in (1)"), "(1 IN (1))")

    def test_hogqlx_row_literals_render_without_tuple_function(self):
        hx_tag = convert_tag_to_hx(ast.HogQLXTag(kind="div", attributes=[]))
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[hx_tag], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="postgres", stack=[select_query]),
        )

        rendered = print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="postgres",
            stack=[prepared_select_query],
        )

        self.assertEqual(rendered, "(%(hogql_val_0)s, %(hogql_val_1)s)")

    def test_comparison_operators(self):
        self.assertEqual(self._expr("a = b"), "(a = b)")
        self.assertEqual(self._expr("a != b"), "(a != b)")
        self.assertEqual(self._expr("a LIKE b"), "(a LIKE b)")
        self.assertEqual(self._expr("a NOT LIKE b"), "(a NOT LIKE b)")
        self.assertEqual(self._expr("a ILIKE b"), "(a ILIKE b)")
        self.assertEqual(self._expr("a NOT ILIKE b"), "(a NOT ILIKE b)")
        self.assertEqual(self._expr("a IN (b, c, d)"), "(a IN (b, c, d))")
        self.assertEqual(self._expr("a NOT IN (b, c, d)"), "(a NOT IN (b, c, d))")
        self.assertEqual(self._expr("a ~ b"), "(a ~ b)")
        self.assertEqual(self._expr("a !~ b"), "(a !~ b)")
        self.assertEqual(self._expr("a ~* b"), "(a ~* b)")
        self.assertEqual(self._expr("a !~* b"), "(a !~* b)")
        self.assertEqual(self._expr("a > b"), "(a > b)")
        self.assertEqual(self._expr("a >= b"), "(a >= b)")
        self.assertEqual(self._expr("a < b"), "(a < b)")
        self.assertEqual(self._expr("a <= b"), "(a <= b)")

    def test_arithmetic_operators(self):
        self.assertEqual(self._expr("a + b"), "(a + b)")
        self.assertEqual(self._expr("a - b"), "(a - b)")
        self.assertEqual(self._expr("a * b"), "(a * b)")
        self.assertEqual(self._expr("a / b"), "(a / b)")
        self.assertEqual(self._expr("a % b"), "(a % b)")

    def test_logical_operators(self):
        self.assertEqual(self._expr("a AND b"), "((a) AND (b))")
        self.assertEqual(self._expr("a OR b"), "((a) OR (b))")
        self.assertEqual(self._expr("NOT a"), "(NOT a)")

    def test_unknown_comparison_operator_raises_error(self):
        query: ast.CompareOperation = cast(ast.CompareOperation, parse_expr("a = b"))

        # Manually set an invalid operator to test error handling
        class MockOp:
            name = "INVALID_OP"

        query.op = cast(ast.CompareOperationOp, MockOp())

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[query], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))

        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="postgres", stack=[select_query]),
        )

        self.assertRaises(
            ImpossibleASTError,
            lambda: print_prepared_ast(
                prepared_select_query.select[0],
                context=context,
                dialect="postgres",
                stack=[prepared_select_query],
            ),
        )

    def test_postgres_style_cast(self):
        self.assertEqual(self._expr("123::int"), "CAST(123 AS int)")
        self.assertEqual(self._expr("123.45::float"), "CAST(123.45 AS float)")
        self.assertEqual(self._expr("'2024-01-01'::date"), "CAST(%(hogql_val_0)s AS date)")
        self.assertEqual(self._expr("event::int"), "CAST(events.event AS int)")
        self.assertEqual(self._expr("event::text"), "CAST(events.event AS text)")
        self.assertEqual(self._expr("event::boolean"), "CAST(events.event AS boolean)")
        self.assertEqual(self._expr("event::INT"), "CAST(events.event AS int)")
        self.assertEqual(self._expr("(1 + 2)::int"), "CAST((1 + 2) AS int)")
        self.assertEqual(
            self._expr("CAST(event AS STRUCT(a INTEGER, b VARCHAR))"),
            'CAST(events.event AS "struct(a integer, b varchar)")',
        )
        self.assertEqual(
            self._expr("CAST(event AS DECIMAL(10, 2))"),
            'CAST(events.event AS "decimal(10, 2)")',
        )

    @parameterized.expand(
        [
            # SQL injection attempts
            ("int); DROP TABLE users; --", '"int); DROP TABLE users; --"'),
            ("text' OR '1'='1", "\"text' OR '1'='1\""),
            ("int; DELETE FROM events;", '"int; DELETE FROM events;"'),
            ("varchar(100)); --", '"varchar(100)); --"'),
            # Quote escaping
            ('int"test', '"int""test"'),
            ("int'test", '"int\'test"'),
            # Backslash handling
            ("int\\test", '"int\\test"'),
            # Unicode/special chars
            ("int\x00test", '"int\x00test"'),
            # Newlines and whitespace injection
            ("int\nDROP TABLE", '"int\nDROP TABLE"'),
            ("int\rtest", '"int\rtest"'),
            # Simple identifiers should not be quoted
            ("varchar", "varchar"),
            ("integer", "integer"),
        ]
    )
    def test_type_cast_typename_escape(self, type_name, expected_escaped):
        node = ast.TypeCast(
            expr=ast.Constant(value=123),
            type_name=type_name,
        )
        self.assertEqual(self._expr(node), f"CAST(123 AS {expected_escaped})")

    @parameterized.expand(
        [
            # SQL injection attempts — mirrors test_type_cast_typename_escape for TRY_CAST.
            ("int); DROP TABLE users; --", '"int); DROP TABLE users; --"'),
            ("text' OR '1'='1", "\"text' OR '1'='1\""),
            ("int; DELETE FROM events;", '"int; DELETE FROM events;"'),
            ("varchar(100)); --", '"varchar(100)); --"'),
            # Quote escaping
            ('int"test', '"int""test"'),
            ("int'test", '"int\'test"'),
            # Backslash handling
            ("int\\test", '"int\\test"'),
            # Unicode/special chars
            ("int\x00test", '"int\x00test"'),
            # Newlines and whitespace injection
            ("int\nDROP TABLE", '"int\nDROP TABLE"'),
            ("int\rtest", '"int\rtest"'),
            # Simple identifiers should not be quoted
            ("varchar", "varchar"),
            ("integer", "integer"),
        ]
    )
    def test_try_cast_typename_escape(self, type_name, expected_escaped):
        node = ast.TryCast(
            expr=ast.Constant(value=123),
            type_name=type_name,
        )
        self.assertEqual(self._expr(node), f"TRY_CAST(123 AS {expected_escaped})")

    @parameterized.expand(
        [
            (
                "basic",
                "WITH stats(a, b) AS (SELECT event, timestamp FROM events) SELECT a, b FROM stats",
                "stats(a, b) AS",
            ),
            (
                "single column",
                "WITH single(x) AS (SELECT event FROM events) SELECT x FROM single",
                "single(x) AS",
            ),
            (
                "reserved word as column name",
                "WITH stats(select, from) AS (SELECT event, timestamp FROM events) SELECT stats.select FROM stats",
                'stats("select", "from") AS',
            ),
            (
                "used in join",
                """
                WITH cte1(id, val) AS (SELECT event, timestamp FROM events),
                     cte2(id, val) AS (SELECT event, timestamp FROM events)
                SELECT c1.id, c2.val
                FROM cte1 AS c1
                JOIN cte2 AS c2 ON c1.id = c2.id
                """,
                "cte1(id, val) AS",
            ),
        ]
    )
    def test_cte_column_name_list(self, _name: str, query: str, expected_fragment: str):
        result = self._select(query)
        self.assertIn(expected_fragment, result)

    def test_with_recursive(self):
        query = "WITH RECURSIVE events_cte AS (SELECT id FROM events) SELECT id FROM events_cte"
        self.assertEqual(
            self._select(query),
            "WITH RECURSIVE events_cte AS (SELECT id FROM events) SELECT id FROM events_cte LIMIT 50000",
        )

    def test_with_recursive_self_referencing(self):
        query = "WITH RECURSIVE nums AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM nums WHERE n < 5) SELECT n FROM nums"
        self.assertEqual(
            self._select(query),
            "WITH RECURSIVE nums AS (SELECT 1 AS n UNION ALL SELECT (nums.n + 1) FROM nums WHERE (nums.n < 5)) "
            "SELECT nums.n FROM nums LIMIT 50000",
        )

    def test_cte_materialization_hint_materialized(self):
        query = "WITH events_cte AS MATERIALIZED (SELECT id FROM events) SELECT id FROM events_cte"
        self.assertEqual(
            self._select(query),
            "WITH events_cte AS MATERIALIZED (SELECT id FROM events) SELECT id FROM events_cte LIMIT 50000",
        )

    def test_cte_materialization_hint_not_materialized(self):
        query = "WITH events_cte AS NOT MATERIALIZED (SELECT id FROM events) SELECT id FROM events_cte"
        self.assertEqual(
            self._select(query),
            "WITH events_cte AS NOT MATERIALIZED (SELECT id FROM events) SELECT id FROM events_cte LIMIT 50000",
        )

    def test_cte_using_key_single_column(self):
        query = "WITH RECURSIVE x(a, b) USING KEY (a) AS (SELECT 1 AS a, 2 AS b UNION ALL SELECT a + 1, b FROM x WHERE a < 5) SELECT * FROM x"
        result = self._select(query)
        self.assertIn("USING KEY", result)
        self.assertIn("x(a, b) USING KEY (a) AS", result)

    def test_cte_using_key_multiple_columns(self):
        query = "WITH RECURSIVE x(a, b, c) USING KEY (a, b) AS (SELECT 1 AS a, 2 AS b, 3 AS c UNION ALL SELECT a + 1, b, c FROM x WHERE a < 5) SELECT * FROM x"
        result = self._select(query)
        self.assertIn("x(a, b, c) USING KEY (a, b) AS", result)

    def test_cte_using_key_without_column_name_list(self):
        query = "WITH RECURSIVE x USING KEY (a) AS (SELECT 1 AS a UNION ALL SELECT a + 1 FROM x WHERE a < 5) SELECT * FROM x"
        result = self._select(query)
        self.assertIn("USING KEY (a) AS", result)

    def test_select_qualify(self):
        result = self._select("SELECT row_number() OVER () AS rn FROM events QUALIFY rn = 1")
        self.assertIn("QUALIFY", result)
        self.assertIn("rn", result)

    def test_select_qualify_with_having(self):
        result = self._select("SELECT 1 FROM events HAVING 1 == 1 QUALIFY 1 == 1")
        self.assertIn("HAVING", result)
        self.assertIn("QUALIFY", result)

    def test_values_query(self):
        self.assertEqual(
            self._select("SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS v (id, name)"),
            "SELECT v.id, v.name FROM (VALUES (1, %(hogql_val_0)s), (2, %(hogql_val_1)s)) AS v (id, name) LIMIT 50000",
        )

    def test_values_query_no_alias_columns(self):
        self.assertEqual(
            self._select("SELECT * FROM (VALUES (1, 'hello')) AS v"),
            "SELECT v.col0, v.col1 FROM (VALUES (1, %(hogql_val_0)s)) AS v (col0, col1) LIMIT 50000",
        )

    def test_values_query_no_alias(self):
        self.assertEqual(
            self._select("SELECT * FROM (VALUES (1, 'george', 'created'), (2, 'jack', 'deleted'))"),
            "SELECT values.col0, values.col1, values.col2 FROM (VALUES (1, %(hogql_val_0)s, %(hogql_val_1)s), (2, %(hogql_val_2)s, %(hogql_val_3)s)) AS values (col0, col1, col2) LIMIT 50000",
        )

    def test_values_query_clickhouse_raises_error(self):
        from posthog.hogql.errors import QueryError

        with self.assertRaises(QueryError):
            self._select("SELECT * FROM (VALUES (1, 'a')) AS v(id, name)", dialect="clickhouse")

    def test_unpivot_prints_basic(self):
        self.assertEqual(
            self._select("SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event))"),
            "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (events.event)) LIMIT 50000",
        )

    def test_unpivot_prints_with_alias(self):
        self.assertEqual(
            self._select("SELECT field_name FROM events UNPIVOT (field_value FOR field_name IN (event)) AS u"),
            "SELECT u.field_name FROM events UNPIVOT (field_value FOR field_name IN (events.event)) AS u LIMIT 50000",
        )

    def test_unpivot_prints_with_table_alias(self):
        self.assertEqual(
            self._select("SELECT field_name FROM events e UNPIVOT (field_value FOR field_name IN (event))"),
            "SELECT field_name FROM events AS e UNPIVOT (field_value FOR field_name IN (e.event)) LIMIT 50000",
        )

    def test_unpivot_prints_with_multiple_in_columns(self):
        self.assertEqual(
            self._select(
                "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event, uuid))"
            ),
            "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (events.event, events.uuid)) LIMIT 50000",
        )

    def test_unpivot_prints_include_nulls(self):
        result = self._select(
            "SELECT field_name, field_value FROM events UNPIVOT INCLUDE NULLS (field_value FOR field_name IN (event))"
        )
        self.assertIn("UNPIVOT INCLUDE NULLS", result)

    def test_unpivot_prints_with_where_group_order(self):
        result = self._select(
            "SELECT field_name, count() FROM events UNPIVOT (field_value FOR field_name IN (event)) "
            "WHERE field_value != '' GROUP BY field_name ORDER BY field_name"
        )
        self.assertIn("UNPIVOT", result)
        self.assertIn("WHERE", result)
        self.assertIn("GROUP BY", result)
        self.assertIn("ORDER BY", result)

    def test_unpivot_join_prints(self):
        self.assertEqual(
            self._select(
                "SELECT field_name, field_value FROM events JOIN events AS e2 ON 1 "
                "UNPIVOT (field_value FOR field_name IN (events.event))"
            ),
            "SELECT field_name, field_value FROM events JOIN events AS e2 ON 1 UNPIVOT (field_value FOR field_name IN (events.event)) LIMIT 50000",
        )

    def test_unpivot_clickhouse_raises_error(self):
        from posthog.hogql.errors import QueryError

        with self.assertRaises(QueryError):
            self._select(
                "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event))",
                dialect="clickhouse",
            )

    def test_replace_columns_prints(self):
        self.assertEqual(
            self._select(
                "SELECT (* REPLACE (1 AS event)) FROM (SELECT 2 AS event, 3 AS other) AS s",
            ),
            "SELECT 1 AS event, s.other FROM (SELECT 2 AS event, 3 AS other) AS s LIMIT 50000",
        )

    def test_replace_columns_with_exclude_prints(self):
        self.assertEqual(
            self._select(
                "SELECT (* EXCLUDE (b) REPLACE (0 AS a)) FROM (SELECT 1 AS a, 2 AS b, 3 AS c) AS s",
            ),
            "SELECT 0 AS a, s.c FROM (SELECT 1 AS a, 2 AS b, 3 AS c) AS s LIMIT 50000",
        )

    def test_replace_columns_with_column_aliases_prints(self):
        self.assertEqual(
            self._select(
                "SELECT (* REPLACE (0 AS a)) FROM (SELECT 1 AS customer_id, 2 AS b, 3 AS c) AS customers (a, b, c)",
            ),
            "SELECT 0 AS a, customers.b, customers.c FROM (SELECT 1 AS customer_id, 2 AS b, 3 AS c) AS customers (a, b, c) LIMIT 50000",
        )

    def test_intersect_all(self):
        result = self._select("select 1 as id intersect all select 2 as id")
        self.assertIn("INTERSECT ALL", result)

    def test_except_all(self):
        result = self._select("select 1 as id except all select 2 as id")
        self.assertIn("EXCEPT ALL", result)

    # -- ClickHouse → Postgres function translation tests --

    @parameterized.expand(
        [
            # Renames
            ("ifNull", "ifNull(1, 2)", "COALESCE(1, 2)"),
            ("replaceAll", "replaceAll('abc', 'a', 'z')", "REPLACE(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s)"),
            (
                "replaceRegexpAll",
                "replaceRegexpAll('abc', 'a', 'z')",
                "REGEXP_REPLACE(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s)",
            ),
            ("toTypeName", "toTypeName(1)", "pg_typeof(1)"),
            ("now", "now()", "NOW()"),
            ("any", "any(event)", "MIN(events.event)"),
            ("startsWith", "startsWith('hello', 'he')", "starts_with(%(hogql_val_0)s, %(hogql_val_1)s)"),
            ("rand", "rand()", "random()"),
            ("generateSeries", "generateSeries(1, 10, 1)", "generate_series(1, 10, 1)"),
            # Type conversions
            ("toDate", "toDate('2024-01-01')", "CAST(%(hogql_val_0)s AS DATE)"),
            ("toDateTime", "toDateTime('2024-01-01')", "CAST(%(hogql_val_0)s AS TIMESTAMP)"),
            ("toDateTime_tz", "toDateTime('2024-01-01', 'UTC')", "CAST(%(hogql_val_0)s AS TIMESTAMP)"),
            ("toString", "toString(123)", "CAST(123 AS TEXT)"),
            ("toInt", "toInt(3.14)", "CAST(3.14 AS BIGINT)"),
            ("toFloat", "toFloat(1)", "CAST(1 AS DOUBLE PRECISION)"),
            ("toFloatOrZero", "toFloatOrZero('1.5')", "CAST(%(hogql_val_0)s AS DOUBLE PRECISION)"),
            ("toFloatOrDefault", "toFloatOrDefault('1.5')", "CAST(%(hogql_val_0)s AS DOUBLE PRECISION)"),
            ("toIntOrZero", "toIntOrZero('42')", "CAST(%(hogql_val_0)s AS BIGINT)"),
            ("toBool", "toBool(1)", "CAST(1 AS BOOLEAN)"),
            ("toUUID", "toUUID('abc')", "CAST(%(hogql_val_0)s AS UUID)"),
            ("toDecimal", "toDecimal(1, 2)", "CAST(1 AS DECIMAL)"),
            ("toDateTime64", "toDateTime64('2024-01-01', 3)", "CAST(%(hogql_val_0)s AS TIMESTAMP)"),
            # Date extraction
            ("toYear", "toYear(now())", "EXTRACT(YEAR FROM NOW())"),
            ("toQuarter", "toQuarter(now())", "EXTRACT(QUARTER FROM NOW())"),
            ("toMonth", "toMonth(now())", "EXTRACT(MONTH FROM NOW())"),
            ("toDayOfMonth", "toDayOfMonth(now())", "EXTRACT(DAY FROM NOW())"),
            ("toDayOfWeek", "toDayOfWeek(now())", "EXTRACT(ISODOW FROM NOW())"),
            ("toDayOfYear", "toDayOfYear(now())", "EXTRACT(DOY FROM NOW())"),
            ("toHour", "toHour(now())", "EXTRACT(HOUR FROM NOW())"),
            ("toMinute", "toMinute(now())", "EXTRACT(MINUTE FROM NOW())"),
            ("toSecond", "toSecond(now())", "EXTRACT(SECOND FROM NOW())"),
            ("toISOWeek", "toISOWeek(now())", "EXTRACT(WEEK FROM NOW())"),
            ("toISOYear", "toISOYear(now())", "EXTRACT(ISOYEAR FROM NOW())"),
            ("toUnixTimestamp", "toUnixTimestamp(now())", "CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT)"),
            ("toYYYYMM", "toYYYYMM(now())", "CAST(TO_CHAR(NOW(), 'YYYYMM') AS INTEGER)"),
            ("toYYYYMMDD", "toYYYYMMDD(now())", "CAST(TO_CHAR(NOW(), 'YYYYMMDD') AS INTEGER)"),
            ("toYYYYMMDDhhmmss", "toYYYYMMDDhhmmss(now())", "CAST(TO_CHAR(NOW(), 'YYYYMMDDHH24MISS') AS BIGINT)"),
            # Date truncation (toStartOf* tested separately in test_to_start_of_*)
            ("toMonday", "toMonday(now())", "CAST(DATE_TRUNC('week', NOW()) AS DATE)"),
            (
                "toLastDayOfMonth",
                "toLastDayOfMonth(now())",
                "CAST((DATE_TRUNC('month', NOW()) + INTERVAL '1 month' - INTERVAL '1 day') AS DATE)",
            ),
            (
                "toLastDayOfWeek",
                "toLastDayOfWeek(now())",
                "CAST((DATE_TRUNC('week', NOW()) + INTERVAL '6 day') AS DATE)",
            ),
            # Date generators
            ("today", "today()", "CURRENT_DATE"),
            ("yesterday", "yesterday()", "(CURRENT_DATE - INTERVAL '1 day')"),
            # Intervals
            ("toIntervalSecond", "toIntervalSecond(60)", "(60 * INTERVAL '1 second')"),
            ("toIntervalMinute", "toIntervalMinute(30)", "(30 * INTERVAL '1 minute')"),
            ("toIntervalHour", "toIntervalHour(3)", "(3 * INTERVAL '1 hour')"),
            ("toIntervalDay", "toIntervalDay(7)", "(7 * INTERVAL '1 day')"),
            ("toIntervalWeek", "toIntervalWeek(2)", "(2 * INTERVAL '1 week')"),
            ("toIntervalMonth", "toIntervalMonth(6)", "(6 * INTERVAL '1 month')"),
            ("toIntervalQuarter", "toIntervalQuarter(1)", "(1 * INTERVAL '3 month')"),
            ("toIntervalYear", "toIntervalYear(1)", "(1 * INTERVAL '1 year')"),
            # Date arithmetic
            ("addDays", "addDays(now(), 7)", "(NOW() + 7 * INTERVAL '1 day')"),
            ("addHours", "addHours(now(), 3)", "(NOW() + 3 * INTERVAL '1 hour')"),
            ("addMonths", "addMonths(now(), 1)", "(NOW() + 1 * INTERVAL '1 month')"),
            ("addYears", "addYears(now(), 2)", "(NOW() + 2 * INTERVAL '1 year')"),
            ("subtractDays", "subtractDays(now(), 7)", "(NOW() - 7 * INTERVAL '1 day')"),
            ("subtractMonths", "subtractMonths(now(), 3)", "(NOW() - 3 * INTERVAL '1 month')"),
            (
                "dateDiff",
                "dateDiff('day', now(), now())",
                "DATE_PART(%(hogql_val_0)s, CAST(NOW() AS TIMESTAMP) - CAST(NOW() AS TIMESTAMP))",
            ),
            # Conditional
            ("if", "if(1, 'yes', 'no')", "CASE WHEN 1 THEN %(hogql_val_0)s ELSE %(hogql_val_1)s END"),
            (
                "multiIf",
                "multiIf(1, 'a', 0, 'b', 'c')",
                "CASE WHEN 1 THEN %(hogql_val_0)s WHEN 0 THEN %(hogql_val_1)s ELSE %(hogql_val_2)s END",
            ),
            # Null/empty
            ("empty", "empty('test')", "(%(hogql_val_0)s IS NULL OR %(hogql_val_0)s = '')"),
            ("notEmpty", "notEmpty('test')", "(%(hogql_val_0)s IS NOT NULL AND %(hogql_val_0)s != '')"),
            ("isNull", "isNull(1)", "(1 IS NULL)"),
            ("isNotNull", "isNotNull(1)", "(1 IS NOT NULL)"),
            ("assumeNotNull", "assumeNotNull(1)", "1"),
            ("toNullable", "toNullable(1)", "1"),
            # JSON
            (
                "JSONExtractInt",
                "JSONExtractInt('{}', 'key')",
                "CAST(json_extract_path_text(%(hogql_val_0)s, %(hogql_val_1)s) AS INTEGER)",
            ),
            (
                "JSONExtractFloat",
                "JSONExtractFloat('{}', 'key')",
                "CAST(json_extract_path_text(%(hogql_val_0)s, %(hogql_val_1)s) AS DOUBLE PRECISION)",
            ),
            (
                "JSONExtractBool",
                "JSONExtractBool('{}', 'key')",
                "CAST(json_extract_path_text(%(hogql_val_0)s, %(hogql_val_1)s) AS BOOLEAN)",
            ),
            (
                "JSONExtractUInt",
                "JSONExtractUInt('{}', 'key')",
                "CAST(json_extract_path_text(%(hogql_val_0)s, %(hogql_val_1)s) AS INTEGER)",
            ),
            # String
            ("match", "match('hello', 'h.*o')", "(%(hogql_val_0)s ~ %(hogql_val_1)s)"),
            ("splitByString", "splitByString(',', 'a,b,c')", "STRING_TO_ARRAY(%(hogql_val_1)s, %(hogql_val_0)s)"),
            ("splitByChar", "splitByChar(',', 'a,b,c')", "STRING_TO_ARRAY(%(hogql_val_1)s, %(hogql_val_0)s)"),
            (
                "endsWith",
                "endsWith('hello', 'lo')",
                "(RIGHT(%(hogql_val_0)s, LENGTH(%(hogql_val_1)s)) = %(hogql_val_1)s)",
            ),
            (
                "replaceOne",
                "replaceOne('abc', 'a', 'z')",
                "REGEXP_REPLACE(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s)",
            ),
            (
                "replaceRegexpOne",
                "replaceRegexpOne('abc', 'a+', 'z')",
                "REGEXP_REPLACE(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s)",
            ),
            # Math
            ("e", "e()", "exp(1)"),
            ("log2", "log2(8)", "log(2, 8)"),
            # Aggregation
            ("uniq", "uniq(1)", "COUNT(DISTINCT 1)"),
            ("uniqExact", "uniqExact(1)", "COUNT(DISTINCT 1)"),
            # Case-insensitive function lookup
            ("now_uppercase", "NOW()", "NOW()"),
            ("count_uppercase", "COUNT(event)", "count(events.event)"),
            ("if_uppercase", "IF(1, 2, 3)", "CASE WHEN 1 THEN 2 ELSE 3 END"),
        ]
    )
    def test_clickhouse_functions_translate_to_postgres(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            ("countIf_1arg", "countIf(1)", "count(*) FILTER (WHERE 1)"),
            ("countIf_2arg", "countIf(event, 1)", "count(events.event) FILTER (WHERE 1)"),
            ("sumIf", "sumIf(1, 1)", "sum(1) FILTER (WHERE 1)"),
            ("avgIf", "avgIf(1, 1)", "avg(1) FILTER (WHERE 1)"),
            ("minIf", "minIf(1, 1)", "min(1) FILTER (WHERE 1)"),
            ("maxIf", "maxIf(1, 1)", "max(1) FILTER (WHERE 1)"),
            ("anyIf", "anyIf(1, 1)", "MIN(1) FILTER (WHERE 1)"),
            ("uniqIf", "uniqIf(1, 1)", "COUNT(DISTINCT 1) FILTER (WHERE 1)"),
            ("uniqExactIf", "uniqExactIf(1, 1)", "COUNT(DISTINCT 1) FILTER (WHERE 1)"),
            ("groupArrayIf", "groupArrayIf(1, 1)", "ARRAY_AGG(1) FILTER (WHERE 1)"),
        ]
    )
    def test_if_combinator_functions(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            ("argMax", "argMax(1, 2)"),
            ("argMin", "argMin(1, 2)"),
            ("range", "range(1, 10)"),
        ]
    )
    def test_unmapped_clickhouse_functions_raise_error(self, _name: str, expr: str):
        with self.assertRaises(QueryError) as ctx:
            self._expr(expr)
        self.assertIn("not supported in the Postgres dialect", str(ctx.exception))
        self.assertNotIn("ClickHouse", str(ctx.exception))

    @parameterized.expand(
        [
            ("count", "count()"),
            ("sum", "sum(1)"),
            ("abs", "abs(1)"),
            ("lower", "lower('x')"),
            ("coalesce", "coalesce(1, 2)"),
            ("row_number", "row_number()"),
            ("greatest", "greatest(1, 2)"),
        ]
    )
    def test_standard_sql_functions_pass_through(self, _name: str, expr: str):
        result = self._expr(expr)
        self.assertIsNotNone(result)

    def test_connection_metadata_functions_pass_through(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            direct_postgres_connection_metadata={"available_functions": ["date_bin"]},
        )

        self.assertEqual(
            self._expr("date_bin(toIntervalHour(1), now(), now())", context=context),
            "date_bin((1 * INTERVAL '1 hour'), NOW(), NOW())",
        )

    @parameterized.expand(
        [
            ("semicolon_injection", "evil; DROP TABLE users --"),
            ("parenthesis_injection", "evil()--"),
            ("spaces", "read text"),
            ("dash_char", "read-text"),
            ("dot_char", "schema.func"),
        ]
    )
    def test_invalid_function_names_rejected(self, _name: str, func_name: str):
        node = ast.Call(name=func_name, args=[ast.Constant(value=1)])
        with self.assertRaises(QueryError):
            self._expr(node)

    def test_connection_metadata_filters_invalid_function_names(self):
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            direct_postgres_connection_metadata={"available_functions": ["date_bin", "evil;drop", "read text"]},
        )
        # date_bin should work, but the invalid names should be filtered out
        self.assertEqual(
            self._expr("date_bin(toIntervalHour(1), now(), now())", context=context),
            "date_bin((1 * INTERVAL '1 hour'), NOW(), NOW())",
        )


class TestDuckDBPrinter(BaseTest):
    """DuckDB printer tests — focused on the DuckDB-specific overrides vs Postgres.

    The DuckDB dialect inherits most of its behavior from PostgresPrinter, so the
    full PG test surface is implicitly covered via inheritance. The assertions below
    lock in the specific places DuckDB output diverges from PG.
    """

    maxDiff = None

    def _expr(
        self,
        query: ast.Expr | str,
        context: Optional[HogQLContext] = None,
        settings: Optional[HogQLQuerySettings] = None,
        backend: HogQLParserBackend = "cpp-json",
    ) -> str:
        node = parse_expr(query, backend=backend) if isinstance(query, str) else query
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(
            select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])), settings=settings
        )
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="duckdb", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="duckdb",
            stack=[prepared_select_query],
        )

    def _select(
        self,
        query: str,
        context: Optional[HogQLContext] = None,
        placeholders: Optional[dict[str, ast.Expr]] = None,
    ) -> str:
        return prepare_and_print_ast(
            parse_select(query, placeholders=placeholders, backend="cpp-json"),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "duckdb",
        )[0]

    @parameterized.expand(
        [
            ("any_renames_to_any_value", "any(event)", "any_value(events.event)"),
            ("toTypeName_renames_to_typeof", "toTypeName(event)", "typeof(events.event)"),
            (
                "formatDateTime_renames_to_strftime",
                "formatDateTime(timestamp, '%Y-%m-%d')",
                "strftime(events.timestamp, %(hogql_val_0)s)",
            ),
            (
                "endsWith_renames_to_ends_with",
                "endsWith(event, '_done')",
                "ends_with(events.event, %(hogql_val_0)s)",
            ),
        ]
    )
    def test_function_renames(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_smoke_basic_select(self):
        self.assertEqual(
            self._select("SELECT event FROM events"),
            "SELECT events.event FROM events LIMIT 50000",
        )

    def test_identifier_no_truncation(self):
        # PG would truncate a >63-char generated alias containing double underscores into a SHA-suffixed
        # name via ``_print_identifier``'s truncation heuristic. The separate ``escape_postgres_identifier``
        # length error applies to overlong identifiers that don't hit that heuristic. DuckDB leaves it intact.
        long_name = "a_really_long_table_name_that_would_force_pg_to_truncate__here"
        long_name += "_even_further_past_63_chars"
        self.assertGreater(len(long_name), 63)
        from posthog.hogql.printer.duckdb import DuckDBPrinter

        printer = DuckDBPrinter(context=HogQLContext(team_id=self.team.pk))
        # Simple alphanumeric identifier — returned verbatim without quoting.
        self.assertEqual(printer._print_identifier(long_name), long_name)

    @parameterized.expand(
        [
            ("anti",),
            ("asof",),
            ("attach",),
            ("detach",),
            ("exclude",),
            ("install",),
            ("load",),
            ("macro",),
            ("pivot",),
            ("positional",),
            ("pragma",),
            ("qualify",),
            ("replace",),
            ("sample",),
            ("semi",),
            ("summarize",),
            ("unpivot",),
        ]
    )
    def test_duckdb_extra_reserved_keywords_are_quoted(self, name: str):
        # DuckDB reserves these even though Postgres doesn't — an unquoted identifier would parse-error.
        from posthog.hogql.printer.duckdb import DuckDBPrinter

        printer = DuckDBPrinter(context=HogQLContext(team_id=self.team.pk))
        self.assertEqual(printer._print_identifier(name), f'"{name}"')

    def test_percent_in_identifier_rejected_postgres_family(self):
        # ``%`` in an identifier would confuse psycopg's parameter-placeholder scanning.
        from posthog.hogql.printer.duckdb import DuckDBPrinter
        from posthog.hogql.printer.postgres import PostgresPrinter

        ctx = HogQLContext(team_id=self.team.pk)
        for printer in (DuckDBPrinter(context=ctx), PostgresPrinter(context=ctx)):
            with self.assertRaisesMessage(QueryError, 'is not permitted as it contains the "%" character'):
                printer._print_identifier("bad%name")
