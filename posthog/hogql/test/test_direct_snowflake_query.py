from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import snowflake.connector
from parameterized import parameterized

from posthog.hogql.direct_connection import validate_snowflake_account_id
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor, snowflake_error_to_message, snowflake_field_type_to_clickhouse_type

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

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
            "posthog.hogql.query.validate_direct_snowflake_source_config",
            return_value=(implementation, MagicMock()),
        ):
            with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                response = executor.execute()

        executed_statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(executed_statements[0].startswith("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS"))
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

        with patch("posthog.hogql.query.DIRECT_SNOWFLAKE_MAX_ROWS", 3):
            with patch(
                "posthog.hogql.query.validate_direct_snowflake_source_config",
                return_value=(implementation, MagicMock()),
            ):
                with patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error"):
                    with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                        executor.execute()

    @parameterized.expand(
        [
            ("delete", "DELETE FROM CUSTOMER WHERE C_ID = 1"),
            ("insert", "INSERT INTO CUSTOMER VALUES (1)"),
            ("update", "UPDATE CUSTOMER SET C_NAME = 'x'"),
            ("drop", "DROP TABLE CUSTOMER"),
            ("multiple_statements", "SELECT 1; DROP TABLE CUSTOMER"),
            ("merge", "MERGE INTO CUSTOMER USING staging ON CUSTOMER.C_ID = staging.id WHEN MATCHED THEN DELETE"),
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

        with patch("posthog.hogql.query.validate_direct_snowflake_source_config") as mock_validate:
            with self.assertRaises(ExposedHogQLError):
                executor.execute()

        # The statement is rejected before any connection is opened.
        mock_validate.assert_not_called()
        self.assertIsNone(executor.direct_sql)
