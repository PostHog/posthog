"""Tests for printing HogQL to the MySQL dialect."""

from typing import Optional, cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast


class TestMySQLPrinter(BaseTest):
    maxDiff = None

    def _expr(
        self,
        query: ast.Expr | str,
        context: Optional[HogQLContext] = None,
    ) -> str:
        node = parse_expr(query, backend="cpp-json") if isinstance(query, str) else query
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="mysql", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="mysql",
            stack=[prepared_select_query],
        )

    @parameterized.expand(
        [
            ("is_null", "event is null", "(events.event IS NULL)"),
            ("is_not_null", "event is not null", "(events.event IS NOT NULL)"),
            ("ilike", "event ilike 'a'", "(LOWER(events.event) LIKE LOWER(%(hogql_val_0)s))"),
            ("not_ilike", "event not ilike 'a'", "(LOWER(events.event) NOT LIKE LOWER(%(hogql_val_0)s))"),
            ("regex", "event =~ 'a.*'", "REGEXP_LIKE(events.event, %(hogql_val_0)s, 'c')"),
            ("not_regex", "event !~ 'a.*'", "(NOT REGEXP_LIKE(events.event, %(hogql_val_0)s, 'c'))"),
            ("iregex", "event =~* 'a.*'", "REGEXP_LIKE(events.event, %(hogql_val_0)s, 'i')"),
            ("null_safe_eq", "event <=> 'a'", "(events.event <=> %(hogql_val_0)s)"),
            ("is_not_distinct_from", "event is not distinct from 'a'", "(events.event <=> %(hogql_val_0)s)"),
            ("is_distinct_from", "event is distinct from 'a'", "(NOT (events.event <=> %(hogql_val_0)s))"),
            ("modulo", "1 % 2", "MOD(1, 2)"),
        ]
    )
    def test_mysql_operators(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            ("start_of_day", "toStartOfDay(timestamp)", "CAST(DATE(events.timestamp) AS DATETIME)"),
            ("start_of_year", "toStartOfYear(timestamp)", "MAKEDATE(YEAR(events.timestamp), 1)"),
            (
                "start_of_month",
                "toStartOfMonth(timestamp)",
                "DATE_SUB(DATE(events.timestamp), INTERVAL (DAYOFMONTH(events.timestamp) - 1) DAY)",
            ),
            (
                "start_of_week",
                "toStartOfWeek(timestamp, 3)",
                "DATE_SUB(DATE(events.timestamp), INTERVAL WEEKDAY(events.timestamp) DAY)",
            ),
            ("date_diff", "dateDiff('day', timestamp, now())", "TIMESTAMPDIFF(DAY, events.timestamp, NOW())"),
            (
                "date_trunc",
                "date_trunc('hour', timestamp)",
                "DATE_ADD(DATE(events.timestamp), INTERVAL HOUR(events.timestamp) HOUR)",
            ),
            ("to_year", "toYear(timestamp)", "EXTRACT(YEAR FROM events.timestamp)"),
            ("to_unix", "toUnixTimestamp(timestamp)", "UNIX_TIMESTAMP(events.timestamp)"),
            ("add_days", "addDays(timestamp, 7)", "DATE_ADD(events.timestamp, INTERVAL (7) DAY)"),
            ("interval_add", "timestamp + toIntervalDay(1)", "(events.timestamp + INTERVAL (1) DAY)"),
        ]
    )
    def test_mysql_date_functions(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    @parameterized.expand(
        [
            ("to_string", "CAST(1 AS TEXT)", "CAST(1 AS CHAR)"),
            ("to_int", "CAST('1' AS BIGINT)", "CAST(%(hogql_val_0)s AS SIGNED)"),
            ("to_float", "CAST('1' AS FLOAT)", "CAST(%(hogql_val_0)s AS DOUBLE)"),
            ("to_datetime", "CAST('2020-01-01' AS TIMESTAMP)", "CAST(%(hogql_val_0)s AS DATETIME)"),
        ]
    )
    def test_mysql_casts(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_mysql_cast_unsupported_type(self):
        with self.assertRaisesMessage(QueryError, "Unsupported CAST target"):
            self._expr("CAST(1 AS Array(String))")

    @parameterized.expand(
        [
            ("count_if", "countIf(1 = 1)", "COUNT(CASE WHEN (1 = 1) THEN 1 END)"),
            ("sum_if", "sumIf(1, 2 = 2)", "SUM(CASE WHEN (2 = 2) THEN 1 END)"),
            ("uniq", "uniq(event)", "COUNT(DISTINCT events.event)"),
            ("if_null", "ifNull(event, 'a')", "IFNULL(events.event, %(hogql_val_0)s)"),
            ("if_", "if(1 = 1, 'a', 'b')", "CASE WHEN (1 = 1) THEN %(hogql_val_0)s ELSE %(hogql_val_1)s END"),
            (
                "simple_case",
                "CASE event WHEN '$pageview' THEN event ELSE '' END",
                "CASE events.event WHEN %(hogql_val_0)s THEN events.event ELSE %(hogql_val_1)s END",
            ),
            (
                "starts_with",
                "startsWith(event, 'a')",
                "(LEFT(events.event, CHAR_LENGTH(%(hogql_val_0)s)) = %(hogql_val_0)s)",
            ),
            ("position", "position(event, 'a')", "LOCATE(%(hogql_val_0)s, events.event)"),
        ]
    )
    def test_mysql_functions(self, _name: str, expr: str, expected: str):
        self.assertEqual(self._expr(expr), expected)

    def test_mysql_unsupported_function_raises(self):
        with self.assertRaisesMessage(QueryError, "is not supported in the MySQL dialect"):
            self._expr("arrayJoin([1])")

    def test_mysql_percentile_raises(self):
        with self.assertRaisesMessage(QueryError, "not supported in the MySQL dialect"):
            self._expr("percentile_cont(0.5) WITHIN GROUP (ORDER BY timestamp)")

    def test_mysql_identifier_escaping(self):
        from posthog.hogql.printer.mysql import MySQLPrinter

        printer = MySQLPrinter(context=HogQLContext(team_id=self.team.pk))
        self.assertEqual(printer._print_identifier("foo"), "foo")
        self.assertEqual(printer._print_identifier("select"), "`select`")
        self.assertEqual(printer._print_identifier("weird name"), "`weird name`")
        self.assertEqual(printer._print_identifier("back`tick"), "`back``tick`")

    def test_mysql_percent_in_identifier_rejected(self):
        from posthog.hogql.printer.mysql import MySQLPrinter

        printer = MySQLPrinter(context=HogQLContext(team_id=self.team.pk))
        with self.assertRaisesMessage(QueryError, 'is not permitted as it contains the "%" character'):
            printer._print_identifier("bad%name")
