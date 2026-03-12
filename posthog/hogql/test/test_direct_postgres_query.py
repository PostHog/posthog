from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import psycopg
from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.query import HogQLQueryExecutor, postgres_error_to_message, postgres_oid_to_clickhouse_type

from posthog.temporal.data_imports.sources.postgres.postgres import SSL_REQUIRED_AFTER_DATE

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


class TestDirectPostgresQuery(APIBaseTest):
    @parameterized.expand(
        [
            ("timestamp", 1114, "DateTime"),
            ("timestamptz", 1184, "DateTime64(6, 'UTC')"),
            ("int4", 23, "Int32"),
            ("int8", 20, "Int64"),
            ("unknown", 999999, "String"),
            ("none", None, "String"),
        ]
    )
    def test_postgres_oid_to_clickhouse_type(self, _name: str, oid: int | None, expected: str):
        self.assertEqual(postgres_oid_to_clickhouse_type(oid), expected)

    def test_generate_sql_for_direct_postgres_table_does_not_require_team_id_field(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT * FROM without_team_id",
            team=self.team,
            connection_id=str(source.id),
        )

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("ph3.without_team_id", sql)
        self.assertNotIn(".team_id", sql)
        self.assertEqual(executor.direct_postgres_source_id, str(source.id))

    def test_generate_sql_for_aliased_direct_postgres_table(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT activitylog.id FROM posthog_activitylog AS activitylog",
            team=self.team,
            connection_id=str(source.id),
        )

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("ph3.posthog_activitylog", sql)
        self.assertIn("activitylog", sql)
        self.assertEqual(executor.direct_postgres_source_id, str(source.id))

    def test_generate_sql_for_direct_postgres_table_inside_cte(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="""
            WITH dashboard_cte AS (
                SELECT id
                FROM posthog_dashboard
            )
            SELECT id
            FROM dashboard_cte
            """,
            team=self.team,
            connection_id=str(source.id),
        )

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("dashboard_cte", sql)
        self.assertIn("ph3.posthog_dashboard", sql)
        self.assertEqual(executor.direct_postgres_source_id, str(source.id))

    def test_direct_query_requires_selected_connection(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(query="SELECT * FROM postgres.ph3.without_team_id", team=self.team)

        with self.assertRaises(QueryError) as error:
            executor.generate_clickhouse_sql()

        self.assertEqual(str(error.exception), "Unknown table `postgres.ph3.without_team_id`.")

    def test_mixed_direct_and_clickhouse_query_without_connection_rejects_clickhouse_printing(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT dashboard.id FROM postgres.ph3.posthog_dashboard AS dashboard JOIN events ON 1 = 1",
            team=self.team,
        )

        with self.assertRaises(QueryError) as error:
            executor.generate_clickhouse_sql()

        self.assertEqual(str(error.exception), "Unknown table `postgres.ph3.posthog_dashboard`.")

    def test_selected_connection_prioritizes_matching_direct_source_for_canonical_table_name(self):
        first_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id_1",
            connection_id="connection_id_1",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="first",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "first_schema",
            },
        )
        second_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id_2",
            connection_id="connection_id_2",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="second",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "second_schema",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            external_data_source=first_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            external_data_source=second_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_team",
            team=self.team,
            connection_id=str(second_source.id),
        )

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("FROM\n    second_schema.posthog_team", sql)
        self.assertEqual(executor.direct_postgres_source_id, str(second_source.id))

    def test_selected_connection_rejects_clickhouse_only_tables(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        executor = HogQLQueryExecutor(
            query="SELECT * FROM persons",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaises(QueryError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "Unknown table `persons`.")

    def test_selected_connection_uses_direct_tables_named_like_posthog_tables(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="persons",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        events_executor = HogQLQueryExecutor(
            query="SELECT id FROM events",
            team=self.team,
            connection_id=str(source.id),
        )
        persons_executor = HogQLQueryExecutor(
            query="SELECT id FROM persons",
            team=self.team,
            connection_id=str(source.id),
        )

        events_sql, _events_context = events_executor.generate_clickhouse_sql()
        persons_sql, _persons_context = persons_executor.generate_clickhouse_sql()

        self.assertIn("FROM\n    ph3.events", events_sql)
        self.assertIn("FROM\n    ph3.persons", persons_sql)
        self.assertEqual(events_executor.direct_postgres_source_id, str(source.id))
        self.assertEqual(persons_executor.direct_postgres_source_id, str(source.id))

    @patch("posthog.hogql.query.psycopg.connect")
    def test_selected_connection_allows_table_less_sql(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.fetchall.return_value = [(1,)]
        column = MagicMock(type_code=23)
        column.name = "value"
        mocked_cursor.description = [column]
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT 1 AS value",
            team=self.team,
            connection_id=str(source.id),
        )

        response = executor.execute()

        self.assertEqual(response.results, [(1,)])
        self.assertEqual(executor.direct_postgres_source_id, str(source.id))
        assert executor.direct_postgres_sql is not None
        self.assertIn("1 AS value", executor.direct_postgres_sql)
        self.assertIn("LIMIT 100", executor.direct_postgres_sql)

    def test_selected_connection_rejects_disabled_direct_tables(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        table = DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="posthog_dashboard",
            team=self.team,
            source=source,
            table=table,
            should_sync=False,
        )

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "Unknown table `posthog_dashboard`.")

    def test_execute_direct_postgres_query_raises_user_error_for_missing_source(self):
        missing_source_id = str(uuid4())
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, connection_id=missing_source_id)
        executor.direct_postgres_sql = "SELECT 1"
        executor.direct_postgres_source_id = missing_source_id

        with self.assertRaises(ExposedHogQLError) as error:
            executor._execute_direct_postgres_query()

        self.assertEqual(str(error.exception), "Connection not found or has been deleted")

    def test_postgres_error_to_message_uses_primary_message(self):
        error = psycopg.errors.GroupingError(
            'column "posthog_dashboard.name" must appear in the GROUP BY clause or be used in an aggregate function'
        )
        self.assertEqual(
            postgres_error_to_message(error),
            'column "posthog_dashboard.name" must appear in the GROUP BY clause or be used in an aggregate function',
        )

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_blocks_internal_host(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "Hosts with internal IP addresses are not allowed")
        mock_connect.assert_not_called()

    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_exposes_database_errors(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "name": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.execute.side_effect = psycopg.errors.GroupingError(
            'column "posthog_dashboard.name" must appear in the GROUP BY clause or be used in an aggregate function'
        )
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT name, count(id) FROM posthog_dashboard LIMIT 100",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertIn("must appear in the GROUP BY clause", str(error.exception))
        self.assertEqual(mock_connect.call_args.kwargs["connect_timeout"], 15)
        self.assertEqual(
            mock_connect.call_args.kwargs["options"],
            "-c default_transaction_read_only=on -c statement_timeout=60000",
        )

    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_uses_custom_statement_timeout(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.fetchall.return_value = [(1,)]
        column = MagicMock(type_code=23)
        column.name = "id"
        mocked_cursor.description = [column]
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
            settings=HogQLGlobalSettings(max_execution_time=12),
        )

        executor.execute()

        self.assertEqual(
            mock_connect.call_args.kwargs["options"], "-c default_transaction_read_only=on -c statement_timeout=12000"
        )
        self.assertTrue(any(timing.k.endswith("/postgres_execute") for timing in executor.timings.to_list()))

    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_records_postgres_execute_timing(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.fetchall.return_value = [(1,)]
        column = MagicMock(type_code=23)
        column.name = "id"
        mocked_cursor.description = [column]
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        response = executor.execute()

        self.assertTrue(any(timing.k.endswith("/postgres_execute") for timing in response.timings or []))

    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_reraises_unexpected_errors(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.execute.side_effect = RuntimeError("boom")
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        with self.assertRaises(RuntimeError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "boom")

    @override_settings(DEBUG=False, TEST=False)
    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_uses_required_sslmode_for_new_sources(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )
        source.created_at = SSL_REQUIRED_AFTER_DATE + timedelta(days=1)
        source.save(update_fields=["created_at"])

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.fetchall.return_value = [(1,)]
        column = MagicMock(type_code=23)
        column.name = "id"
        mocked_cursor.description = [column]
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        executor.execute()

        self.assertEqual(mock_connect.call_args.kwargs["sslmode"], "require")

    @override_settings(DEBUG=False, TEST=False)
    @patch("posthog.hogql.query.psycopg.connect")
    def test_execute_direct_postgres_query_adds_ssl_cert_paths_for_postwh_hosts(self, mock_connect):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            job_inputs={
                "host": "db.us.postwh.com",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "ph3",
            },
        )
        source.created_at = SSL_REQUIRED_AFTER_DATE - timedelta(days=1)
        source.save(update_fields=["created_at"])

        DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        mocked_cursor = MagicMock()
        mocked_cursor.fetchall.return_value = [(1,)]
        column = MagicMock(type_code=23)
        column.name = "id"
        mocked_cursor.description = [column]
        mocked_connection = MagicMock()
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
        mock_connect.return_value.__enter__.return_value = mocked_connection

        executor = HogQLQueryExecutor(
            query="SELECT id FROM posthog_dashboard LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        executor.execute()

        self.assertEqual(mock_connect.call_args.kwargs["sslmode"], "require")
        self.assertEqual(mock_connect.call_args.kwargs["sslcert"], "/tmp/no.txt")
        self.assertEqual(mock_connect.call_args.kwargs["sslkey"], "/tmp/no.txt")
        self.assertEqual(mock_connect.call_args.kwargs["sslrootcert"], "/tmp/no.txt")
