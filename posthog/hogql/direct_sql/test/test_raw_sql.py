from collections.abc import Callable

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from sqlparse.exceptions import SQLParseError

from posthog.hogql.direct_sql.bigquery_adapter import ensure_read_only_raw_bigquery_statement
from posthog.hogql.direct_sql.clickhouse_adapter import ensure_read_only_raw_clickhouse_statement
from posthog.hogql.direct_sql.motherduck_adapter import ensure_read_only_raw_motherduck_statement
from posthog.hogql.direct_sql.mysql_adapter import ensure_read_only_raw_mysql_statement
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.direct_sql.redshift_adapter import ensure_read_only_raw_redshift_statement
from posthog.hogql.direct_sql.snowflake_adapter import ensure_read_only_raw_snowflake_statement
from posthog.hogql.direct_sql.trino_adapter import ensure_read_only_raw_trino_statement
from posthog.hogql.errors import ExposedHogQLError


class TestDirectSQLQuoting(SimpleTestCase):
    @parameterized.expand(
        [
            ("postgres", r"SELECT '\\logs\\' AS label"),
            ("duckdb", r"SELECT '\logs\' AS label"),
            ("redshift", r"SELECT '\\logs\\' AS label"),
            ("trino", r"SELECT '\logs\' AS label"),
            ("mysql", r"SELECT 'folder\\report' AS label"),
            ("clickhouse", r"SELECT 'folder\\report' AS label"),
            ("snowflake", r"SELECT 'folder\\report' AS label"),
            ("bigquery", r"SELECT r'''folder\report; 'sample' ''' AS label"),
            ("postgres", "SELECT $label$one; 'two'$label$ AS label"),
            ("duckdb", "SELECT $label$one; 'two'$label$ AS label"),
            ("snowflake", "SELECT $$one; 'two'$$ AS label"),
            ("postgres", r"SELECT E'one\'two' AS label"),
            ("duckdb", r"SELECT E'one\'two' AS label"),
            ("mysql", "SELECT 17 # ; SELECT 29\n"),
            ("bigquery", 'SELECT """one; \'two\'""" AS label'),
            ("postgres", "SELECT " + " + ".join(["17"] * 1000)),
        ]
    )
    def test_accepts_dialect_literals(self, dialect: str, sql: str) -> None:
        self.assertEqual(ensure_single_direct_statement(sql, dialect=dialect), sql)

    @parameterized.expand(
        [
            (dialect,)
            for dialect in ["postgres", "duckdb", "redshift", "trino", "mysql", "clickhouse", "snowflake", "bigquery"]
        ]
    )
    def test_counts_statements_after_literals(self, dialect: str) -> None:
        sql = r"SELECT 'folder\\' AS label; SELECT 'marker' AS value"
        with self.assertRaises(ExposedHogQLError):
            ensure_single_direct_statement(sql, dialect=dialect)

    @parameterized.expand(
        [
            ("postgres", "SELECT 'unfinished"),
            ("duckdb", "SELECT $label$unfinished"),
            ("trino", "SELECT /* unfinished"),
            ("bigquery", 'SELECT """unfinished'),
            ("postgres", "SELECT 17 {# ; SELECT 29 #}"),
            ("mysql", "SELECT 17--2; SELECT 29"),
            ("postgres", r"SELECT 'one\'two' AS label"),
            ("redshift", r"SELECT 'one\'two' AS label"),
            ("mysql", r"SELECT 'one\'two' AS label"),
        ]
    )
    def test_rejects_invalid_or_ambiguous_boundaries(self, dialect: str, sql: str) -> None:
        with self.assertRaises(ExposedHogQLError):
            ensure_single_direct_statement(sql, dialect=dialect)

    @parameterized.expand([("postgres",), ("redshift",), ("mysql",)])
    def test_requires_consistent_session_quoting(self, dialect: str) -> None:
        with self.assertRaisesMessage(ExposedHogQLError, "quoting must be unambiguous"):
            ensure_single_direct_statement(r"SELECT '\' AS label -- '", dialect=dialect)

    @parameterized.expand([("grouping_limit", SQLParseError), ("recursion_limit", RecursionError)])
    def test_exposes_grouping_errors(self, _name: str, error: type[Exception]) -> None:
        with patch("posthog.hogql.direct_sql.raw_sql.group", side_effect=error("limit reached")):
            with self.assertRaisesMessage(ExposedHogQLError, "too complex to validate"):
                ensure_read_only_raw_motherduck_statement("SELECT 17")

    @parameterized.expand(
        [
            ("duckdb", ensure_read_only_raw_motherduck_statement, "read_text('example.txt')"),
            ("clickhouse", ensure_read_only_raw_clickhouse_statement, "file('example.csv', 'CSV')"),
            ("redshift", ensure_read_only_raw_redshift_statement, "set_config('example', 'value', false)"),
            ("snowflake", ensure_read_only_raw_snowflake_statement, "last_query_id()"),
            ("mysql", ensure_read_only_raw_mysql_statement, "load_file('example.txt')"),
            ("duckdb_quoted", ensure_read_only_raw_motherduck_statement, "\"read_text\"('example.txt')"),
            ("clickhouse_quoted", ensure_read_only_raw_clickhouse_statement, "\"file\"('example.csv', 'CSV')"),
            ("redshift_quoted", ensure_read_only_raw_redshift_statement, "\"set_config\"('example', 'value', false)"),
            ("snowflake_quoted", ensure_read_only_raw_snowflake_statement, '"LAST_QUERY_ID"()'),
            ("snowflake_system_quoted", ensure_read_only_raw_snowflake_statement, '"SYSTEM$EXAMPLE"()'),
            ("mysql_quoted", ensure_read_only_raw_mysql_statement, "`load_file`('example.txt')"),
        ]
    )
    def test_checks_functions_after_literals(self, _name: str, validate: Callable[[str], str], call: str) -> None:
        sql = r"SELECT 'folder\\' AS label, " + call + " AS value, 'marker' AS note"
        with self.assertRaises(ExposedHogQLError):
            validate(sql)

    @parameterized.expand(
        [
            ("duckdb", ensure_read_only_raw_motherduck_statement),
            ("clickhouse", ensure_read_only_raw_clickhouse_statement),
            ("redshift", ensure_read_only_raw_redshift_statement),
            ("snowflake", ensure_read_only_raw_snowflake_statement),
            ("mysql", ensure_read_only_raw_mysql_statement),
            ("trino", ensure_read_only_raw_trino_statement),
            ("bigquery", ensure_read_only_raw_bigquery_statement),
            ("mysql_quoted_into", ensure_read_only_raw_mysql_statement, "SELECT `INTO` FROM example_rows"),
            ("mysql_quoted_alias", ensure_read_only_raw_mysql_statement, "SELECT `FOR` AS `UPDATE` FROM example_rows"),
            (
                "qualified_keyword",
                ensure_read_only_raw_motherduck_statement,
                'SELECT example.update FROM (SELECT 17 AS "update") AS example',
            ),
            (
                "keyword_qualifier",
                ensure_read_only_raw_motherduck_statement,
                'SELECT update.value FROM (SELECT 17 AS value) AS "update"',
            ),
        ]
    )
    def test_preserves_read_only_queries(
        self,
        _name: str,
        validate: Callable[[str], str],
        sql: str = r"WITH labels AS (SELECT 'folder\\report' AS label) SELECT * FROM labels WHERE label LIKE '%\_%'",
    ) -> None:
        self.assertEqual(validate(sql), sql)

    @parameterized.expand(
        [
            ("inline", "SELECT 17 /*! + 29 */"),
            ("after_terminator", "SELECT 17; /*! SELECT 29 */"),
            ("mariadb", "SELECT 17 /*M! + 29 */"),
            ("quoted_call", "SELECT \"load_file\"('example.txt')"),
        ]
    )
    def test_rejects_mysql_special_forms(self, _name: str, sql: str) -> None:
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_mysql_statement(sql)
