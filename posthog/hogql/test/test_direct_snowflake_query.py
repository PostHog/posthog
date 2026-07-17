from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import snowflake.connector
from parameterized import parameterized

from posthog.hogql.direct_sql.snowflake_adapter import (
    snowflake_error_to_message,
    snowflake_field_type_to_clickhouse_type,
    validate_snowflake_account_id,
)
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.snowflake_connection_cache import (
    cached_snowflake_connection,
    clear_thread_local_snowflake_connections,
)

from products.warehouse_sources.backend.facade.models import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig

# Snowflake connector type codes (indices into FIELD_ID_TO_NAME). cursor.description
# reports the integer code, not a name — see snowflake_field_type_to_clickhouse_type.
FIXED = 0
REAL = 1
TEXT = 2
DATE = 3
TIMESTAMP = 4
VARIANT = 5
TIMESTAMP_LTZ = 6
TIMESTAMP_TZ = 7
TIMESTAMP_NTZ = 8
OBJECT = 9
ARRAY = 10
BINARY = 11
TIME = 12
BOOLEAN = 13
GEOGRAPHY = 14
GEOMETRY = 15
VECTOR = 16
MAP = 17


class TestDirectSnowflakeQuery(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The connection cache is thread-local module state; isolate each test.
        clear_thread_local_snowflake_connections()
        self.addCleanup(clear_thread_local_snowflake_connections)

    def _create_source(self, prefix: str = "wh") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Snowflake",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=prefix,
            connection_metadata={"engine": "snowflake", "database": "DB"},
            job_inputs={
                "account_id": "acme-prod",
                "database": "DB",
                "warehouse": "WH",
                "role": "REPORTING",
                "auth_type": {"selection": "password", "user": "svc", "password": "pw"},
            },
        )

    @parameterized.expand(
        [
            # FIXED covers NUMBER/DECIMAL/INT; scale decides int vs decimal.
            ("number_decimal", FIXED, 2, "Decimal"),
            ("number_integer_scale_0", FIXED, 0, "Int64"),
            ("number_integer_scale_none", FIXED, None, "Int64"),
            ("real_float", REAL, None, "Float64"),
            ("text_varchar", TEXT, None, "String"),
            ("date", DATE, None, "Date"),
            ("time", TIME, None, "String"),
            ("timestamp", TIMESTAMP, None, "DateTime64(6, 'UTC')"),
            ("timestamp_ntz", TIMESTAMP_NTZ, None, "DateTime64(6, 'UTC')"),
            ("timestamp_ltz", TIMESTAMP_LTZ, None, "DateTime64(6, 'UTC')"),
            ("timestamp_tz", TIMESTAMP_TZ, None, "DateTime64(6, 'UTC')"),
            ("boolean", BOOLEAN, None, "Bool"),
            ("variant", VARIANT, None, "String"),
            ("object", OBJECT, None, "String"),
            ("array", ARRAY, None, "String"),
            ("map", MAP, None, "String"),
            ("binary", BINARY, None, "String"),
            ("geography", GEOGRAPHY, None, "String"),
            ("geometry", GEOMETRY, None, "String"),
            ("vector", VECTOR, None, "String"),
            ("unknown_code", 99999, None, "String"),
            ("non_integer_code", "NUMBER", None, "String"),
            ("none_code", None, None, "String"),
        ]
    )
    def test_snowflake_field_type_to_clickhouse_type(
        self, _name: str, type_code: object | None, scale: object | None, expected: str
    ):
        self.assertEqual(snowflake_field_type_to_clickhouse_type(type_code, scale), expected)

    def test_snowflake_error_to_message_uses_server_message(self):
        error = snowflake.connector.errors.ProgrammingError(
            msg="SQL compilation error:\ninvalid identifier 'NOPE'", errno=904
        )
        # ProgrammingError formats args[1] as "<errno>: <msg>"; only the first line is surfaced.
        self.assertEqual(snowflake_error_to_message(error), "000904: SQL compilation error:")

    def test_snowflake_error_to_message_falls_back_to_str(self):
        self.assertEqual(snowflake_error_to_message(Exception("boom\nsecond line")), "boom")

    def test_snowflake_error_to_message_handles_empty(self):
        self.assertEqual(snowflake_error_to_message(Exception("")), "Snowflake query failed.")

    @parameterized.expand(
        [
            ("org_account", "acme-prod_account"),
            ("legacy_dotted", "xy12345.us-east-1.aws"),
            ("with_leading_alnum", "a1b2c3"),
        ]
    )
    def test_validate_snowflake_account_id_accepts_valid(self, _name: str, account_id: str):
        self.assertEqual(validate_snowflake_account_id(account_id), account_id)

    @parameterized.expand(
        [
            ("empty", ""),
            ("none", None),
            ("whitespace", "   "),
            ("scheme", "http://evil.internal"),
            ("slash_path", "acme/../../etc"),
            ("at_sign", "user@host"),
            ("space_inside", "acme prod"),
            ("leading_dot", ".acme"),
        ]
    )
    def test_validate_snowflake_account_id_rejects_invalid(self, _name: str, account_id: str | None):
        with self.assertRaises(ExposedHogQLError):
            validate_snowflake_account_id(account_id)

    def _mock_snowflake_connection(self, rows: list[tuple], description: list[tuple]) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()
        # Direct Snowflake reads through fetchmany (bounded), not fetchall.
        cursor.fetchmany.return_value = rows
        cursor.description = description
        connection = MagicMock()
        connection.is_closed.return_value = False
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.cursor.return_value.__exit__.return_value = False

        implementation = MagicMock()
        implementation.connect.return_value.__enter__.return_value = connection
        implementation.connect.return_value.__exit__.return_value = False
        return implementation, cursor

    def test_execute_sets_statement_timeout_and_maps_types(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT C_ID, C_ACCTBAL FROM CUSTOMER",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        implementation, cursor = self._mock_snowflake_connection(
            rows=[(1, "100.50")],
            description=[
                ("C_ID", FIXED, None, None, None, 0, None),
                ("C_ACCTBAL", FIXED, None, None, 12, 2, None),
            ],
        )

        with patch(
            "posthog.hogql.direct_sql.snowflake_adapter.SnowflakeAdapter.validate_source_config",
            return_value=(implementation, MagicMock()),
        ):
            with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                response = executor.execute()

        executed_statements = [call.args[0] for call in cursor.execute.call_args_list]
        # Read-only is enforced our side: pin single-statement and the statement timeout
        # on the session before the query runs.
        self.assertEqual(executed_statements[0], "ALTER SESSION SET MULTI_STATEMENT_COUNT = 1")
        self.assertTrue(executed_statements[1].startswith("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS"))
        self.assertEqual(executor.direct_dialect, "snowflake")
        self.assertEqual(response.results, [(1, "100.50")])
        # FIXED with scale 0 → Int64; scale 2 → Decimal (the bug that showed C_ACCTBAL as String).
        self.assertEqual(response.types, [("C_ID", "Int64"), ("C_ACCTBAL", "Decimal")])

    def test_execute_rejects_result_over_row_cap(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT C_ID FROM CUSTOMER",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        # fetchmany is asked for cap+1; returning that many signals the cap was exceeded.
        # Patch the cap small so the test doesn't allocate a million rows.
        implementation, _cursor = self._mock_snowflake_connection(
            rows=[(i,) for i in range(4)],
            description=[("C_ID", FIXED, None, None, None, 0, None)],
        )

        with patch("posthog.hogql.direct_sql.snowflake_adapter.DIRECT_SNOWFLAKE_MAX_ROWS", 3):
            with patch(
                "posthog.hogql.direct_sql.snowflake_adapter.SnowflakeAdapter.validate_source_config",
                return_value=(implementation, MagicMock()),
            ):
                with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                    with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                        executor.execute()

    @parameterized.expand(
        [
            # Leading-keyword writes (rejected by the SELECT classification).
            ("delete", "DELETE FROM CUSTOMER WHERE C_ID = 1"),
            ("insert", "INSERT INTO CUSTOMER VALUES (1)"),
            ("update", "UPDATE CUSTOMER SET C_NAME = 'x'"),
            ("drop", "DROP TABLE CUSTOMER"),
            ("create", "CREATE TABLE t (c int)"),
            ("alter", "ALTER TABLE CUSTOMER ADD COLUMN c int"),
            ("truncate", "TRUNCATE TABLE CUSTOMER"),
            ("multiple_statements", "SELECT 1; DROP TABLE CUSTOMER"),
            ("merge", "MERGE INTO CUSTOMER USING staging ON CUSTOMER.C_ID = staging.id WHEN MATCHED THEN DELETE"),
            # Snowflake side-effecting statements that classify as UNKNOWN, not SELECT.
            ("call_procedure", "CALL my_writing_proc()"),
            ("copy_into", "COPY INTO CUSTOMER FROM @my_stage"),
            ("put_file", "PUT file:///tmp/x @my_stage"),
            ("get_file", "GET @my_stage file:///tmp/x"),
            ("grant", "GRANT SELECT ON CUSTOMER TO ROLE reporting"),
            ("use_database", "USE DATABASE other_db"),
            # Writes smuggled into an otherwise SELECT-classified statement.
            ("write_in_subquery", "SELECT * FROM (DELETE FROM CUSTOMER RETURNING C_ID)"),
            ("write_in_cte", "WITH x AS (INSERT INTO CUSTOMER VALUES (1) RETURNING C_ID) SELECT * FROM x"),
            # Side-effecting / session-leaking functions that parse as a plain SELECT.
            ("system_function", "SELECT SYSTEM$CANCEL_QUERY('01a-b-c')"),
            ("system_function_lower", "SELECT system$wait(1)"),
            ("result_scan", "SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-3)))"),
            ("last_query_id", "SELECT LAST_QUERY_ID()"),
        ]
    )
    def test_raw_query_rejects_non_select(self, _name: str, query: str):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        with patch(
            "posthog.hogql.direct_sql.snowflake_adapter.SnowflakeAdapter.validate_source_config"
        ) as mock_validate:
            with self.assertRaises(ExposedHogQLError):
                executor.execute()

        # The statement is rejected before any connection is opened.
        mock_validate.assert_not_called()
        self.assertIsNone(executor.direct_sql)

    @parameterized.expand(
        [
            ("plain_select", "SELECT C_ID FROM CUSTOMER"),
            ("cte_select", "WITH x AS (SELECT 1 AS v) SELECT v FROM x"),
            # UDFs are read-only in Snowflake; a function call in a SELECT is fine.
            ("udf_call", "SELECT my_udf(C_ID) FROM CUSTOMER"),
            # A write keyword inside a string literal must not trip the token scan.
            ("write_word_in_string", "SELECT C_ID FROM CUSTOMER WHERE C_STATUS = 'DELETE'"),
            # A quoted identifier matching a blocked function name is a column, not a call.
            ("quoted_blocked_name_column", 'SELECT "result_scan" FROM CUSTOMER'),
        ]
    )
    def test_raw_query_allows_read_only_selects(self, _name: str, query: str):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        implementation, _cursor = self._mock_snowflake_connection(
            rows=[(1,)],
            description=[("C_ID", FIXED, None, None, None, 0, None)],
        )

        with patch(
            "posthog.hogql.direct_sql.snowflake_adapter.SnowflakeAdapter.validate_source_config",
            return_value=(implementation, MagicMock()),
        ):
            with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                executor.execute()

        # The statement passed the read-only gate and reached execution unchanged.
        self.assertEqual(executor.direct_sql, query)


class TestSnowflakeConnectionCache(unittest.TestCase):
    def setUp(self):
        clear_thread_local_snowflake_connections()
        self.addCleanup(clear_thread_local_snowflake_connections)

    def _impl_and_config(
        self, secret: str = "pw", account: str = "acme-prod"
    ) -> tuple[MagicMock, "SnowflakeSourceConfig", MagicMock]:
        connection = MagicMock()
        connection.is_closed.return_value = False
        cm = MagicMock()
        cm.__enter__.return_value = connection
        cm.__exit__.return_value = False
        implementation = MagicMock()
        implementation.connect.return_value = cm
        auth = SimpleNamespace(selection="password", user="svc", password=secret, private_key=None, passphrase=None)
        config = SimpleNamespace(
            account_id=account, warehouse="WH", database="DB", role="R", schema="PUBLIC", auth_type=auth
        )
        return implementation, cast("SnowflakeSourceConfig", config), connection

    def test_reuses_connection_across_calls(self):
        implementation, config, connection = self._impl_and_config()

        with cached_snowflake_connection(implementation, config) as first:
            self.assertIs(first, connection)
        with cached_snowflake_connection(implementation, config) as second:
            self.assertIs(second, connection)

        implementation.connect.assert_called_once()

    def test_reopens_after_ttl(self):
        implementation, config, _connection = self._impl_and_config()

        with patch("posthog.hogql.snowflake_connection_cache.SNOWFLAKE_CONNECTION_CACHE_TTL_SECONDS", 0):
            with cached_snowflake_connection(implementation, config):
                pass
            with cached_snowflake_connection(implementation, config):
                pass

        self.assertEqual(implementation.connect.call_count, 2)

    def test_reopens_when_connection_reports_closed(self):
        implementation, config, connection = self._impl_and_config()

        with cached_snowflake_connection(implementation, config):
            pass
        connection.is_closed.return_value = True
        with cached_snowflake_connection(implementation, config):
            pass

        self.assertEqual(implementation.connect.call_count, 2)

    def test_evicts_on_connection_level_error(self):
        implementation, config, _connection = self._impl_and_config()

        with self.assertRaises(snowflake.connector.errors.OperationalError):
            with cached_snowflake_connection(implementation, config):
                raise snowflake.connector.errors.OperationalError(msg="connection dropped")
        with cached_snowflake_connection(implementation, config):
            pass

        # The suspect connection was dropped, so the next call reopens.
        self.assertEqual(implementation.connect.call_count, 2)

    def test_keeps_connection_on_sql_error(self):
        implementation, config, _connection = self._impl_and_config()

        with self.assertRaises(snowflake.connector.errors.ProgrammingError):
            with cached_snowflake_connection(implementation, config):
                raise snowflake.connector.errors.ProgrammingError(msg="bad sql")
        with cached_snowflake_connection(implementation, config):
            pass

        # A SQL error leaves the connection healthy, so it's reused.
        implementation.connect.assert_called_once()

    def test_different_credentials_use_separate_connections(self):
        implementation, config_a, _connection = self._impl_and_config(secret="pw-a")
        _implementation_b, config_b, _connection_b = self._impl_and_config(secret="pw-b")

        with cached_snowflake_connection(implementation, config_a):
            pass
        with cached_snowflake_connection(implementation, config_b):
            pass

        self.assertEqual(implementation.connect.call_count, 2)
