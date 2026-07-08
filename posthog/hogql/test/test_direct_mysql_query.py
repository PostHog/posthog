from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import pymysql
from parameterized import parameterized

from posthog.hogql.direct_sql.mysql_adapter import mysql_error_to_message, mysql_field_type_to_clickhouse_type
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.query import HogQLQueryExecutor

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestDirectMySQLQuery(APIBaseTest):
    def _create_source(self, prefix: str = "shop", schema: str = "shop") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="MySQL",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=prefix,
            connection_metadata={"engine": "mysql", "database": schema},
            job_inputs={
                "host": "localhost",
                "port": 3306,
                "database": schema,
                "user": "mysql",
                "password": "mysql",
                "schema": schema,
                "using_ssl": "true",
            },
        )

    def _create_table(
        self,
        source: ExternalDataSource,
        name: str,
        columns: dict[str, Any] | None = None,
    ) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns=columns
            or {
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "email": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "created_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "valid": True},
            },
        )

    @parameterized.expand(
        [
            ("longlong", pymysql.constants.FIELD_TYPE.LONGLONG, "Int64"),
            ("long", pymysql.constants.FIELD_TYPE.LONG, "Int32"),
            ("tiny", pymysql.constants.FIELD_TYPE.TINY, "Int8"),
            ("double", pymysql.constants.FIELD_TYPE.DOUBLE, "Float64"),
            ("newdecimal", pymysql.constants.FIELD_TYPE.NEWDECIMAL, "Decimal"),
            ("datetime", pymysql.constants.FIELD_TYPE.DATETIME, "DateTime"),
            ("date", pymysql.constants.FIELD_TYPE.DATE, "Date"),
            ("varchar", pymysql.constants.FIELD_TYPE.VAR_STRING, "String"),
            ("json", pymysql.constants.FIELD_TYPE.JSON, "String"),
            ("unknown", 99999, "String"),
            ("none", None, "String"),
        ]
    )
    def test_mysql_field_type_to_clickhouse_type(self, _name: str, type_code: int | None, expected: str):
        self.assertEqual(mysql_field_type_to_clickhouse_type(type_code), expected)

    def test_mysql_error_to_message_uses_server_message(self):
        error = pymysql.err.OperationalError(1054, "Unknown column 'nope' in 'field list'")
        self.assertEqual(mysql_error_to_message(error), "Unknown column 'nope' in 'field list'")

    def test_mysql_error_to_message_falls_back_to_str(self):
        self.assertEqual(mysql_error_to_message(Exception("boom")), "boom")

    def test_generate_sql_uses_backticks_and_no_team_id(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT * FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("shop.orders", sql)
        self.assertNotIn(".team_id", sql)
        self.assertEqual(executor.direct_source_id, str(source.id))
        self.assertEqual(executor.direct_dialect, "mysql")

    def test_generate_sql_for_aliased_table(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT o.id FROM orders AS o",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("shop.orders", sql)
        self.assertEqual(executor.direct_dialect, "mysql")

    def test_string_constants_are_parameterized(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE email = 'a@b.com'",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, context = executor.generate_clickhouse_sql()

        self.assertIn("%(hogql_val_0)s", sql)
        self.assertEqual(context.values["hogql_val_0"], "a@b.com")
        self.assertNotIn("a@b.com", sql)

    def test_ilike_is_emulated_with_lower(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE email ILIKE '%test%'",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("LOWER(", sql)
        self.assertIn("LIKE", sql)

    def test_regex_uses_regexp_like(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE email =~ 'test.*'",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("REGEXP_LIKE(", sql)
        self.assertIn("'c'", sql)

    def test_modulo_renders_as_mod_function(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id % 2 FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("MOD(", sql)
        self.assertNotIn("%)", sql)

    def test_to_start_of_day_expands_without_date_trunc(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT toStartOfDay(created_at) FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("CAST(DATE(", sql)
        self.assertNotIn("date_trunc", sql.lower())

    def test_date_diff_uses_timestampdiff(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT dateDiff('day', created_at, now()) FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("TIMESTAMPDIFF(DAY", sql)

    def test_null_safe_eq_renders_mysql_operator(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE email <=> 'a@b.com'",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("<=>", sql)

    def test_unsupported_function_raises(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT arrayJoin([1,2]) FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        with self.assertRaises(QueryError) as ctx:
            executor.generate_clickhouse_sql()
        self.assertIn("not supported in the MySQL dialect", str(ctx.exception))

    def test_full_join_raises(self):
        source = self._create_source()
        self._create_table(source, "orders")
        self._create_table(source, "customers")

        executor = HogQLQueryExecutor(
            query="SELECT orders.id FROM orders FULL JOIN customers ON orders.id = customers.id",
            team=self.team,
            connection_id=str(source.id),
        )
        with self.assertRaises(QueryError) as ctx:
            executor.generate_clickhouse_sql()
        self.assertIn("FULL JOIN is not supported", str(ctx.exception))

    def test_try_cast_raises(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT TRY_CAST(id AS TEXT) FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )
        with self.assertRaises(QueryError):
            executor.generate_clickhouse_sql()

    def test_cannot_mix_direct_sources(self):
        mysql_source = self._create_source()
        self._create_table(mysql_source, "orders")

        other_source = self._create_source(prefix="other", schema="other")
        self._create_table(other_source, "payments")

        executor = HogQLQueryExecutor(
            query="SELECT orders.id FROM orders JOIN payments ON orders.id = payments.id",
            team=self.team,
            connection_id=str(mysql_source.id),
        )
        with self.assertRaises(ExposedHogQLError):
            executor.generate_clickhouse_sql()

    def test_table_less_query_uses_mysql_dialect(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT 1 AS value",
            team=self.team,
            connection_id=str(source.id),
        )
        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("1 AS value", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertEqual(executor.direct_dialect, "mysql")

    def _mock_mysql_connection(self, rows: list[tuple], description: list[tuple]) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        cursor.description = description
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.cursor.return_value.__exit__.return_value = False

        implementation = MagicMock()
        implementation.connect.return_value.__enter__.return_value = connection
        implementation.connect.return_value.__exit__.return_value = False
        return implementation, cursor

    def test_raw_query_routes_to_mysql_executor(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        implementation, cursor = self._mock_mysql_connection(
            rows=[(1,)],
            description=[("1", pymysql.constants.FIELD_TYPE.LONGLONG, None, None, None, None, None)],
        )

        with patch(
            "posthog.hogql.direct_sql.mysql_adapter.MySQLAdapter.validate_source_config",
            return_value=(implementation, MagicMock()),
        ):
            with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                response = executor.execute()

        self.assertEqual(executor.direct_dialect, "mysql")
        self.assertEqual(executor.direct_sql, "SELECT 1")
        self.assertEqual(response.results, [(1,)])
        cursor.execute.assert_any_call("SELECT 1", None)

    def test_raw_query_rejects_multiple_statements(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT 1; DROP TABLE orders",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )
        with self.assertRaises(ExposedHogQLError):
            executor.execute()

    def test_raw_query_allows_cte_select(self):
        source = self._create_source()

        query = "WITH one AS (SELECT 1 AS value) SELECT value FROM one"
        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        implementation, cursor = self._mock_mysql_connection(
            rows=[(1,)],
            description=[("value", pymysql.constants.FIELD_TYPE.LONGLONG, None, None, None, None, None)],
        )

        with patch(
            "posthog.hogql.direct_sql.mysql_adapter.MySQLAdapter.validate_source_config",
            return_value=(implementation, MagicMock()),
        ):
            with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                response = executor.execute()

        self.assertEqual(executor.direct_sql, query)
        self.assertEqual(response.results, [(1,)])
        cursor.execute.assert_any_call(query, None)

    @parameterized.expand(
        [
            ("delete", "DELETE FROM orders WHERE id = 1"),
            ("set_global", "SET GLOBAL max_connections = 1"),
            ("kill", "KILL 1"),
            ("into_outfile", "SELECT * FROM orders INTO OUTFILE '/tmp/orders.csv'"),
            ("into_dumpfile", "SELECT * FROM orders INTO DUMPFILE '/tmp/orders.csv'"),
            ("select_into_variable", "SELECT * FROM orders INTO @orders"),
            ("load_file", "SELECT LOAD_FILE('/etc/passwd')"),
            ("load_file_in_cte", "WITH data AS (SELECT LOAD_FILE('/etc/passwd') AS contents) SELECT * FROM data"),
            ("executable_comment", "SELECT 1 /*!50000 INTO OUTFILE '/tmp/orders.csv' */"),
            ("mariadb_executable_comment", "SELECT 1 /*M!100100 INTO OUTFILE '/tmp/orders.csv' */"),
            ("for_update", "SELECT * FROM orders FOR UPDATE"),
            ("for_share", "SELECT * FROM orders FOR SHARE"),
            ("lock_in_share_mode", "SELECT * FROM orders LOCK IN SHARE MODE"),
        ]
    )
    def test_raw_query_rejects_unsafe_mysql_statements(self, _name: str, query: str):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        with patch("posthog.hogql.direct_sql.mysql_adapter.MySQLAdapter.validate_source_config") as mock_validate:
            with self.assertRaisesRegex(ExposedHogQLError, "Raw MySQL queries must be read-only SELECT statements."):
                executor.execute()

        mock_validate.assert_not_called()
        self.assertIsNone(executor.direct_sql)

    def test_execute_runs_read_only_transaction_and_maps_types(self):
        source = self._create_source()
        self._create_table(source, "orders")

        executor = HogQLQueryExecutor(
            query="SELECT id, email FROM orders",
            team=self.team,
            connection_id=str(source.id),
        )

        cursor = MagicMock()
        cursor.fetchall.return_value = [(1, "a@b.com")]
        cursor.description = [
            ("id", pymysql.constants.FIELD_TYPE.LONGLONG, None, None, None, None, None),
            ("email", pymysql.constants.FIELD_TYPE.VAR_STRING, None, None, None, None, None),
        ]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.cursor.return_value.__exit__.return_value = False

        implementation = MagicMock()
        implementation.connect.return_value.__enter__.return_value = connection
        implementation.connect.return_value.__exit__.return_value = False

        with patch(
            "posthog.hogql.direct_sql.mysql_adapter.MySQLAdapter.validate_source_config",
            return_value=(implementation, MagicMock()),
        ):
            response = executor.execute()

        executed_statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(executed_statements[0].startswith("SET SESSION MAX_EXECUTION_TIME"))
        self.assertEqual(executed_statements[1], "START TRANSACTION READ ONLY")
        self.assertEqual(response.results, [(1, "a@b.com")])
        self.assertEqual(response.types, [("id", "Int64"), ("email", "String")])
