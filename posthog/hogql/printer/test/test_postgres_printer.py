"""Tests for printing HogQL to the Postgres dialect."""

from typing import Optional, cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect, HogQLParserBackend, HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ImpossibleASTError, QueryError
from posthog.hogql.hogqlx import convert_tag_to_hx
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clear_locations

from posthog.models.team.team import WeekStartDay


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

    def test_concat_casts_bound_string_parameters_to_text(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        self.assertEqual(
            self._expr("f'{event} {event}'", context=context),
            "concat(events.event, CAST(%(hogql_val_0)s AS TEXT), events.event)",
        )
        self.assertEqual(context.values, {"hogql_val_0": " "})

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
                "SELECT count(*) FROM events GROUP BY events.event LIMIT 50000",
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
                "SELECT 1 FROM events PIVOT (count(*) FOR events.event IN (%(hogql_val_0)s, %(hogql_val_1)s)) LIMIT 50000",
            ),
            (
                "multiple_columns",
                "SELECT 1 FROM events PIVOT (count() FOR event IN ('a') distinct_id IN (1, 2) GROUP BY timestamp)",
                "SELECT 1 FROM events PIVOT (count(*) FOR events.event IN (%(hogql_val_0)s) events.distinct_id IN (1, 2) GROUP BY events.timestamp) LIMIT 50000",
            ),
            (
                "join",
                "SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN ('a'))",
                "SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count(*) FOR events.event IN (%(hogql_val_0)s)) LIMIT 50000",
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

    @parameterized.expand(
        [
            ("array_access_over_alias", "(1 as x)[1]"),
            ("nullish_array_access_over_alias", "(1 as x)?.[1]"),
            ("property_access_over_alias", "(1 as x).a"),
            ("array_access_over_between", "(1 between 2 and 3)[1]"),
            ("array_access_over_is_distinct_from", "(1 is distinct from 2)[1]"),
        ]
    )
    def test_array_access_over_loose_operand_roundtrips(self, _name: str, source: str):
        """Regression: `[...]` binds tighter than the infix-printed forms (alias,
        BETWEEN, IS DISTINCT FROM), so the printer must parenthesize such an array
        operand — `(1 as x)[1]` used to print as `1 AS x[1]`, which does not parse
        back, and `(1 between 2 and 3)[1]` silently regrouped on reparse."""
        node = parse_expr(source)
        printed = node.to_hogql()
        parsed = parse_expr(printed)
        self.assertEqual(clear_locations(parsed), clear_locations(node), f"AST changed after roundtrip: {printed!r}")
        self.assertEqual(parsed.to_hogql(), printed)

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
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        self.assertEqual(
            self._expr("properties.a.b.c.$browser", context=context),
            "((((events.properties) -> %(hogql_val_0)s) -> %(hogql_val_1)s) -> %(hogql_val_2)s) ->> %(hogql_val_3)s",
        )
        self.assertEqual(list(context.values.values()), ["a", "b", "c", "$browser"])

    def test_json_properties_in_select_render_as_postgres_json_access(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        printed = self._select("SELECT properties.detail.name FROM events", context=context)

        self.assertIn("(events.properties) ->", printed)
        self.assertIn("->> %(hogql_val", printed)
        self.assertIn('AS "properties.detail.name"', printed)
        self.assertIn("name", context.values.values())

    def test_json_property_key_injection_is_parameterized_not_inlined(self):
        # A property key containing a single quote must not break out of the string literal.
        # The ClickHouse ``\'`` escape does not work in Postgres (standard_conforming_strings=on),
        # so the key must be parameterized rather than escape-inlined.
        # The doubled '' is an escaped single quote in HogQL, so the key value contains a literal '.
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        printed = self._expr("properties['x''); DROP TABLE users; --']", context=context)

        self.assertNotIn("DROP TABLE", printed)
        self.assertNotIn("\\'", printed)
        self.assertIn("x'); DROP TABLE users; --", context.values.values())

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
        self.assertEqual(self._expr("a % b"), "MOD(a, b)")

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
            "WITH RECURSIVE nums AS ((SELECT 1 AS n) UNION ALL (SELECT (nums.n + 1) FROM nums WHERE (nums.n < 5))) "
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
            ("toFloatOrDefault", "toFloatOrDefault('1.5', 0)", "CAST(%(hogql_val_0)s AS DOUBLE PRECISION)"),
            ("toIntOrZero", "toIntOrZero('42')", "CAST(%(hogql_val_0)s AS BIGINT)"),
            ("toIntOrDefault", "toIntOrDefault('42', 0)", "CAST(%(hogql_val_0)s AS BIGINT)"),
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
            (
                "simple_case",
                "CASE event WHEN '$pageview' THEN event ELSE '' END",
                "CASE events.event WHEN %(hogql_val_0)s THEN events.event ELSE %(hogql_val_1)s END",
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
