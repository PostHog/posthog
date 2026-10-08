from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from google.api_core import exceptions as google_api_exceptions
from parameterized import parameterized

from posthog.hogql.direct_sql.bigquery_adapter import bigquery_error_to_message, bigquery_field_to_clickhouse_type
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from products.warehouse_sources.backend.facade.models import ExternalDataSource

_FACADE = "products.warehouse_sources.backend.facade.source_management"


class TestDirectBigQueryQuery(APIBaseTest):
    def _create_source(self, prefix: str = "bq") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="BigQuery",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=prefix,
            job_inputs={
                "dataset_id": "analytics",
                "auth_type": {
                    "selection": "key_file",
                    "key_file": {
                        "project_id": "acme-project",
                        "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
                        "private_key_id": "fakekeyid",
                        "client_email": "svc@acme-project.iam.gserviceaccount.com",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    },
                },
            },
        )

    def _mock_bigquery_client(self, rows: list[tuple], schema_fields: list[SimpleNamespace]) -> MagicMock:
        row_iterator = MagicMock()
        row_mocks = []
        for row in rows:
            row_mock = MagicMock()
            row_mock.values.return_value = row
            row_mocks.append(row_mock)
        row_iterator.__iter__.return_value = iter(row_mocks)
        row_iterator.schema = schema_fields

        job = MagicMock()
        job.result.return_value = row_iterator

        client = MagicMock()
        client.query.return_value = job
        return client

    def _patched_execute(self, executor: HogQLQueryExecutor, client: MagicMock):
        config = SimpleNamespace(use_custom_region=None)
        auth = SimpleNamespace(project_id="acme-project", credentials=MagicMock())

        client_cm = MagicMock()
        client_cm.__enter__.return_value = client
        client_cm.__exit__.return_value = False

        with (
            patch(
                "posthog.hogql.direct_sql.bigquery_adapter.BigQueryAdapter.validate_source_config",
                return_value=(MagicMock(), config),
            ),
            patch(f"{_FACADE}.resolve_bigquery_auth", return_value=auth),
            patch(f"{_FACADE}.bigquery_client", return_value=client_cm),
        ):
            return executor.execute()

    def test_execute_returns_rows_and_maps_types(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT id, amount FROM `acme-project.analytics.orders`",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        client = self._mock_bigquery_client(
            rows=[(1, "100.50")],
            schema_fields=[
                SimpleNamespace(name="id", field_type="INTEGER", mode="NULLABLE"),
                SimpleNamespace(name="amount", field_type="NUMERIC", mode="NULLABLE"),
            ],
        )

        response = self._patched_execute(executor, client)

        # The job carries a server-side timeout so an abandoned request doesn't keep billing.
        job_config = client.query.call_args.kwargs["job_config"]
        self.assertIsNotNone(job_config.job_timeout_ms)
        self.assertEqual(response.results, [(1, "100.50")])
        self.assertEqual(response.types, [("id", "Int64"), ("amount", "Decimal")])

    def test_execute_rejects_result_over_row_cap(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT id FROM `acme-project.analytics.orders`",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        client = self._mock_bigquery_client(
            rows=[(i,) for i in range(4)],
            schema_fields=[SimpleNamespace(name="id", field_type="INTEGER", mode="NULLABLE")],
        )

        with patch("posthog.hogql.direct_sql.bigquery_adapter.DIRECT_BIGQUERY_MAX_ROWS", 3):
            with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                self._patched_execute(executor, client)

    def test_raw_query_rejected_when_flag_off(self):
        # The flag is the kill switch: turning it off must stop queries on already-created
        # connections, not just block new ones. It is off by default in tests.
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT id FROM `acme-project.analytics.orders`",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        with self.assertRaisesRegex(ExposedHogQLError, "not enabled"):
            executor.execute()

    def test_hogql_query_against_raw_only_connection_is_rejected(self):
        # Without this guard a HogQL query on a BigQuery connection would be printed in the
        # postgres dialect and shipped to BigQuery.
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaisesRegex(ExposedHogQLError, "raw SQL"):
            executor.execute()

    @parameterized.expand(
        [
            # Leading-keyword writes (rejected by the SELECT classification).
            ("delete", "DELETE FROM `acme.analytics.orders` WHERE id = 1"),
            ("insert", "INSERT INTO `acme.analytics.orders` VALUES (1)"),
            ("update", "UPDATE `acme.analytics.orders` SET name = 'x' WHERE true"),
            ("drop", "DROP TABLE `acme.analytics.orders`"),
            ("create", "CREATE TABLE `acme.analytics.t` (c INT64)"),
            ("alter", "ALTER TABLE `acme.analytics.orders` ADD COLUMN c INT64"),
            ("truncate", "TRUNCATE TABLE `acme.analytics.orders`"),
            ("multiple_statements", "SELECT 1; DROP TABLE `acme.analytics.orders`"),
            ("merge", "MERGE INTO `acme.analytics.orders` USING s ON orders.id = s.id WHEN MATCHED THEN DELETE"),
            # BigQuery side-effecting statements that classify as UNKNOWN, not SELECT.
            ("call_procedure", "CALL `acme.analytics.my_writing_proc`()"),
            ("execute_immediate", "EXECUTE IMMEDIATE 'DELETE FROM `acme.analytics.orders` WHERE true'"),
            ("grant", "GRANT `roles/bigquery.dataViewer` ON TABLE `acme.analytics.orders` TO 'user:x@example.com'"),
            ("begin_script", "BEGIN DELETE FROM `acme.analytics.orders` WHERE true; END"),
            # Writes smuggled into an otherwise SELECT-classified statement.
            ("write_in_cte", "WITH x AS (DELETE FROM `acme.analytics.orders` WHERE true) SELECT 1"),
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

        with patch("posthog.hogql.direct_sql.bigquery_adapter.BigQueryAdapter.validate_source_config") as mock_validate:
            with self.assertRaises(ExposedHogQLError):
                executor.execute()

        # The statement is rejected before any credentials are resolved.
        mock_validate.assert_not_called()
        self.assertIsNone(executor.direct_sql)

    @parameterized.expand(
        [
            ("plain_select", "SELECT id FROM `acme-project.analytics.orders`"),
            ("cte_select", "WITH x AS (SELECT 1 AS v) SELECT v FROM x"),
            # A write keyword inside a string literal must not trip the token scan.
            ("write_word_in_string", "SELECT id FROM `acme-project.analytics.orders` WHERE status = 'DELETE'"),
            # Backtick-quoted project.dataset.table identifiers are BigQuery's native form.
            ("backtick_identifiers", "SELECT `select`.id FROM `acme-project.analytics.orders` AS `select`"),
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

        client = self._mock_bigquery_client(
            rows=[(1,)],
            schema_fields=[SimpleNamespace(name="id", field_type="INTEGER", mode="NULLABLE")],
        )

        self._patched_execute(executor, client)

        # The statement passed the read-only gate and reached execution unchanged.
        self.assertEqual(executor.direct_sql, query)

    @parameterized.expand(
        [
            ("integer_legacy", "INTEGER", "NULLABLE", "Int64"),
            ("int64_standard", "INT64", "NULLABLE", "Int64"),
            ("float_legacy", "FLOAT", "NULLABLE", "Float64"),
            ("numeric", "NUMERIC", "NULLABLE", "Decimal"),
            ("bignumeric", "BIGNUMERIC", "NULLABLE", "Decimal"),
            ("string", "STRING", "NULLABLE", "String"),
            ("boolean_legacy", "BOOLEAN", "NULLABLE", "Bool"),
            ("date", "DATE", "NULLABLE", "Date"),
            ("datetime", "DATETIME", "NULLABLE", "DateTime64(6, 'UTC')"),
            ("timestamp", "TIMESTAMP", "NULLABLE", "DateTime64(6, 'UTC')"),
            ("time", "TIME", "NULLABLE", "String"),
            ("bytes", "BYTES", "NULLABLE", "String"),
            ("record_struct", "RECORD", "NULLABLE", "String"),
            ("json", "JSON", "NULLABLE", "String"),
            ("geography", "GEOGRAPHY", "NULLABLE", "String"),
            ("repeated_is_array", "INTEGER", "REPEATED", "String"),
            ("unknown", "FUTURETYPE", "NULLABLE", "String"),
            ("none_type", None, "NULLABLE", "String"),
        ]
    )
    def test_bigquery_field_to_clickhouse_type(self, _name: str, field_type: str | None, mode: str, expected: str):
        self.assertEqual(bigquery_field_to_clickhouse_type(field_type, mode), expected)

    @parameterized.expand(
        [
            # google.api_core errors carry the clean server message; str() prefixes the code + URL.
            (
                "api_call_error_uses_message",
                google_api_exceptions.BadRequest("Syntax error: Unexpected keyword DELETE at [1:1]"),
                "Syntax error: Unexpected keyword DELETE at [1:1]",
            ),
            ("plain_exception_first_line", Exception("boom\nsecond line"), "boom"),
            ("empty_message", Exception(""), "BigQuery query failed."),
        ]
    )
    def test_bigquery_error_to_message(self, _name: str, error: Exception, expected: str):
        self.assertEqual(bigquery_error_to_message(error), expected)
