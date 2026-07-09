from typing import Any
from uuid import uuid4

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.direct_sql.redshift_adapter import ensure_read_only_raw_redshift_statement
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.direct_redshift import DIRECT_REDSHIFT_URL_PATTERN
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestDirectRedshiftQuery(APIBaseTest):
    def _create_source(self, prefix: str = "shop", schema: str = "public") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Redshift",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=prefix,
            connection_metadata={"engine": "redshift", "database": "dev"},
            job_inputs={
                "host": "localhost",
                "port": 5439,
                "database": "dev",
                "user": "awsuser",
                "password": "redshift",
                "schema": schema,
            },
        )

    def _create_table(self, source: ExternalDataSource, name: str, columns: dict[str, Any] | None = None):
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern=DIRECT_REDSHIFT_URL_PATTERN,
            columns=columns
            or {
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "email": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "created_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "valid": True},
            },
        )

    def test_generate_sql_uses_redshift_dialect_and_schema_qualified_table(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT * FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertEqual(executor.direct_dialect, "redshift")
        self.assertIn("public", sql)
        self.assertIn("orders", sql)
        self.assertNotIn(".team_id", sql)

    def test_shared_postgres_surface_compiles(self):
        # Redshift shares Postgres's date_trunc / ILIKE surface; this guards against the
        # subtractive printer over-blocking the core surface it should keep.
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT toStartOfDay(created_at) FROM orders WHERE email ILIKE '%test%'",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, context = executor.generate_clickhouse_sql()

        self.assertIn("date_trunc('day'", sql)
        self.assertIn("ILIKE", sql)
        # String constants bind as parameters rather than inlining into the SQL.
        self.assertNotIn("%test%", sql)
        self.assertIn("%test%", context.values.values())

    @parameterized.expand(
        [
            ("array_literal", "SELECT [1, 2, 3] FROM orders"),
            ("lambda", "SELECT arrayMap(x -> x + 1, [1, 2]) FROM orders"),
            ("group_array", "SELECT groupArray(id) FROM orders"),
            ("to_start_of_isoyear", "SELECT toStartOfISOYear(created_at) FROM orders"),
            ("uuid_cast", "SELECT toUUID(id) FROM orders"),
            ("count_if_filter", "SELECT countIf(id > 0) FROM orders"),
        ]
    )
    def test_incompatible_constructs_raise(self, _name: str, query: str):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(query=query, team=self.team, connection_id=str(source.id))
        with self.assertRaises(QueryError) as ctx:
            executor.generate_clickhouse_sql()
        self.assertIn("Redshift dialect", str(ctx.exception))

    @parameterized.expand(
        [
            # Redshift has no zero-arg count().
            ("count_star", "SELECT count() FROM orders", "count(*)"),
            # DISTINCT used to be silently dropped, returning plain counts.
            ("count_distinct", "SELECT count(DISTINCT id) FROM orders", "count(DISTINCT "),
            # Redshift CONCAT is two-arg and NULL-propagating; HogQL concat is variadic, NULL→''.
            ("concat_null_safe_chain", "SELECT concat(email, ' ', email) FROM orders", " || COALESCE(CAST("),
            # Redshift rejects the two-arg position() call form.
            ("position_as_strpos", "SELECT position(email, '@') FROM orders", "STRPOS("),
            # Redshift avg(int) truncates to an integer; HogQL avg is float.
            ("avg_cast_to_float", "SELECT avg(id) FROM orders", "avg(CAST("),
            # Redshift `/` on integers truncates; HogQL division is float.
            ("division_cast_to_float", "SELECT id / 2 FROM orders", "AS DOUBLE PRECISION) / "),
        ]
    )
    def test_semantic_rewrites_print_redshift_equivalents(self, _name: str, query: str, expected_fragment: str):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(query=query, team=self.team, connection_id=str(source.id))
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn(expected_fragment, sql)

    def test_set_query_operands_are_parenthesized(self):
        # The default LIMIT is injected into every branch of a set query; Redshift only
        # accepts a per-branch LIMIT on a parenthesized operand.
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders UNION ALL SELECT id FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertRegex(sql, r"\)\s*UNION ALL\s*\(")

    def test_raw_query_result_row_cap(self):
        # A raw passthrough SELECT with no LIMIT must not load an unbounded result set into
        # memory; the adapter reads cap+1 rows and errors when the cap is exceeded.
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        cursor = MagicMock()
        cursor.description = [MagicMock(name="id")]
        cursor.fetchmany.return_value = [(i,) for i in range(4)]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        implementation = MagicMock()
        implementation.connect.return_value.__enter__.return_value = connection

        with patch("posthog.hogql.direct_sql.redshift_adapter.DIRECT_REDSHIFT_MAX_ROWS", 3):
            with patch(
                "posthog.hogql.direct_sql.redshift_adapter.RedshiftAdapter.validate_source_config",
                return_value=(implementation, MagicMock()),
            ):
                with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                    with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                        executor.execute()


class TestEnsureReadOnlyRawRedshiftStatement(unittest.TestCase):
    @parameterized.expand(
        [
            ("plain_select", "SELECT salesid FROM public.sales"),
            # sqlparse must type a CTE statement as SELECT, not over-block it.
            ("cte_select", "WITH t AS (SELECT 1 AS v) SELECT v FROM t"),
            # A write keyword inside a string literal must not trip the token scan.
            ("write_word_in_string", "SELECT 'DELETE' FROM public.sales"),
        ]
    )
    def test_accepts_read_only_selects(self, _name: str, sql: str):
        self.assertEqual(ensure_read_only_raw_redshift_statement(sql), sql)

    @parameterized.expand(
        [
            # Redshift's SELECT ... INTO creates and populates a table while still
            # tokenizing as a SELECT statement — the one write shape with no DML/DDL token.
            ("select_into", "SELECT * INTO backup_sales FROM public.sales"),
            ("dml_in_cte", "WITH d AS (DELETE FROM public.sales RETURNING *) SELECT * FROM d"),
            ("update", "UPDATE public.sales SET qtysold = 0"),
        ]
    )
    def test_rejects_writes(self, _name: str, sql: str):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_redshift_statement(sql)
