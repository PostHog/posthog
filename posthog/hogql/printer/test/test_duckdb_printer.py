"""Tests for printing HogQL to the DuckDB dialect."""

from typing import Optional, cast

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLParserBackend, HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast


class TestDuckDBPrinter(SimpleTestCase):
    """DuckDB printer tests — focused on the DuckDB-specific overrides vs Postgres.

    The DuckDB dialect inherits most of its behavior from PostgresPrinter, so the
    full PG test surface is implicitly covered via inheritance. The assertions below
    lock in the specific places DuckDB output diverges from PG.
    """

    maxDiff = None
    team_id = 1

    def _expr(
        self,
        query: ast.Expr | str,
        context: Optional[HogQLContext] = None,
        settings: Optional[HogQLQuerySettings] = None,
        backend: HogQLParserBackend = "cpp-json",
    ) -> str:
        node = parse_expr(query, backend=backend) if isinstance(query, str) else query
        context = context or HogQLContext(team_id=self.team_id, enable_select_queries=True)
        context.database = context.database or Database()
        if context.restricted_properties is None:
            context.restricted_properties = set()
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
        context = context or HogQLContext(team_id=self.team_id, enable_select_queries=True)
        context.database = context.database or Database()
        if context.restricted_properties is None:
            context.restricted_properties = set()
        return prepare_and_print_ast(
            parse_select(query, placeholders=placeholders, backend="cpp-json"),
            context,
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
            ("argMax_renames_to_arg_max", "argMax(event, timestamp)", "arg_max(events.event, events.timestamp)"),
            ("argMin_renames_to_arg_min", "argMin(event, timestamp)", "arg_min(events.event, events.timestamp)"),
            (
                "dateTrunc_renames_to_date_trunc",
                "dateTrunc('day', timestamp)",
                "date_trunc(%(hogql_val_0)s, events.timestamp)",
            ),
            ("tuple_renames_to_row", "tuple(event, 1)", "row(events.event, 1)"),
            ("range_is_allowed", "range(3)", "range(3)"),
        ]
    )
    def test_function_renames(self, _name: str, expr: str, expected: str) -> None:
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            (
                "argMaxIf_uses_filter",
                "argMaxIf(event, timestamp, event = 'x')",
                "arg_max(events.event, events.timestamp) FILTER (WHERE (events.event = %(hogql_val_0)s))",
            ),
            (
                "argMinIf_uses_filter",
                "argMinIf(event, timestamp, event = 'x')",
                "arg_min(events.event, events.timestamp) FILTER (WHERE (events.event = %(hogql_val_0)s))",
            ),
            (
                "dateAdd_builds_interval",
                "dateAdd('day', 2, timestamp)",
                "date_add(events.timestamp, CAST((CAST(2 AS VARCHAR) || ' ' || CAST(%(hogql_val_0)s AS VARCHAR)) AS INTERVAL))",
            ),
            (
                "dateAdd_accepts_interval",
                "dateAdd(timestamp, toIntervalDay(2))",
                "date_add(events.timestamp, (2 * INTERVAL '1 day'))",
            ),
            (
                "dateAdd_preserves_date_type",
                "dateAdd('day', 2, toDate('2026-08-04'))",
                "CAST(date_add(CAST(%(hogql_val_1)s AS DATE), CAST((CAST(2 AS VARCHAR) || ' ' || CAST(%(hogql_val_0)s AS VARCHAR)) AS INTERVAL)) AS DATE)",
            ),
            (
                "dateTrunc_preserves_date_type",
                "dateTrunc('month', toDate('2026-08-04'))",
                "CAST(date_trunc(%(hogql_val_0)s, CAST(%(hogql_val_1)s AS DATE)) AS DATE)",
            ),
            ("groupUniqArray_uses_distinct_list", "groupUniqArray(event)", "list(DISTINCT events.event)"),
            (
                "groupUniqArrayIf_uses_filter",
                "groupUniqArrayIf(event, event = 'x')",
                "list(DISTINCT events.event) FILTER (WHERE (events.event = %(hogql_val_0)s))",
            ),
            (
                "tupleElement_uses_struct_extract",
                "tupleElement(tuple(1, event), 2)",
                "struct_extract(row(1, events.event), 2)",
            ),
            ("multiply_uses_operator", "multiply(2, 3)", "(2 * 3)"),
            ("not_uses_operator", ast.Call(name="NOT", args=[ast.Constant(value=True)]), "(NOT true)"),
            ("like_uses_operator", "like(event, 'x%')", "(events.event LIKE %(hogql_val_0)s)"),
            ("current_timestamp_uses_keyword", "current_timestamp()", "CURRENT_TIMESTAMP"),
        ]
    )
    def test_function_handlers(self, _name: str, expr: str, expected: str) -> None:
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

        printer = DuckDBPrinter(context=HogQLContext(team_id=self.team_id))
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

        printer = DuckDBPrinter(context=HogQLContext(team_id=self.team_id))
        self.assertEqual(printer._print_identifier(name), f'"{name}"')

    def test_percent_in_identifier_rejected_postgres_family(self):
        # ``%`` in an identifier would confuse psycopg's parameter-placeholder scanning.
        from posthog.hogql.printer.duckdb import DuckDBPrinter
        from posthog.hogql.printer.postgres import PostgresPrinter

        ctx = HogQLContext(team_id=self.team_id)
        for printer in (DuckDBPrinter(context=ctx), PostgresPrinter(context=ctx)):
            with self.assertRaisesMessage(QueryError, 'is not permitted as it contains the "%" character'):
                printer._print_identifier("bad%name")

    def test_dollar_prefixed_property_renders_as_jsonpath_member(self):
        # DuckDB's JSON arrow operator reads a key beginning with `$` as a JSONPath root marker, so the
        # inherited Postgres form `(properties) ->> '$ai_session_id'` fails to bind on duckgres with
        # "JSON path error near 'ai_session_id'". Every PostHog built-in property is `$`-prefixed, so
        # DuckDB must emit the key as a quoted JSONPath member instead: `$."$ai_session_id"`.
        context = HogQLContext(team_id=self.team_id, enable_select_queries=True)
        printed = self._expr("properties.$ai_session_id", context=context)
        self.assertEqual(printed, "(events.properties) ->> %(hogql_val_0)s")
        self.assertEqual(list(context.values.values()), ['$."$ai_session_id"'])

    def test_nested_property_renders_as_single_jsonpath_member(self):
        # A nested chain collapses into one JSONPath bound as a single value, not a chain of arrows.
        context = HogQLContext(team_id=self.team_id, enable_select_queries=True)
        printed = self._expr("properties.a.b.$browser", context=context)
        self.assertEqual(printed, "(events.properties) ->> %(hogql_val_0)s")
        self.assertEqual(list(context.values.values()), ['$."a"."b"."$browser"'])

    def test_json_property_key_with_quote_is_escaped_in_jsonpath(self):
        # A `"` in the key would terminate the quoted JSONPath member early, so it must be backslash
        # escaped. The whole path is still a bound value, so this is not a SQL-injection vector.
        context = HogQLContext(team_id=self.team_id, enable_select_queries=True)
        self._expr("properties['a\"b']", context=context)
        self.assertEqual(list(context.values.values()), ['$."a\\"b"'])

    def test_repeated_property_access_reuses_one_placeholder(self):
        # DuckDB rejects `GROUP BY <expr>` when the same JSON path is bound to a different placeholder
        # in the SELECT than in the GROUP BY — it can't prove the two parameterized expressions are
        # equal. Repeated identical reads must collapse to a single bound value so the printed
        # expressions match textually.
        context = HogQLContext(team_id=self.team_id, enable_select_queries=True)
        printed = self._select(
            "SELECT properties.$ai_session_id AS s, count() AS n FROM events GROUP BY properties.$ai_session_id",
            context=context,
        )
        self.assertEqual(list(context.values.values()).count('$."$ai_session_id"'), 1)
        # the SELECT and GROUP BY reference the very same placeholder token
        self.assertEqual(printed.count("(events.properties) ->> %(hogql_val_0)s"), 2)
