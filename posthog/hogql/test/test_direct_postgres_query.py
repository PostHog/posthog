from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import psycopg
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor, postgres_error_to_message, postgres_oid_to_clickhouse_type

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

    def _build_direct_table_type(self) -> ast.TableType:
        return ast.TableType(
            table=DirectPostgresTable(
                name="postgres.ph3.ph3_postgres_posthog_activitylog",
                fields={},
                postgres_schema="ph3",
                postgres_table_name="ph3_postgres_posthog_activitylog",
                external_data_source_id="source-id",
            )
        )

    @parameterized.expand(
        [
            (
                "unaliased_table",
                _build_direct_table_type,
            ),
            (
                "aliased_table",
                lambda test_case: ast.TableAliasType(
                    alias="activitylog",
                    table_type=test_case._build_direct_table_type(),
                ),
            ),
        ]
    )
    def test_extract_direct_postgres_source_ids(self, _name: str, table_type_factory):
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team)
        table_type = table_type_factory(self)
        query_type = ast.SelectQueryType(tables={"postgres.ph3.ph3_postgres_posthog_activitylog": table_type})

        source_ids = executor._extract_direct_postgres_sources_from_type(query_type)

        self.assertEqual(source_ids, {"source-id"})

    @parameterized.expand(
        [
            (
                "all_direct_tables",
                {
                    "postgres.ph3.ph3_postgres_posthog_activitylog": _build_direct_table_type,
                },
                True,
            ),
            (
                "mixed_direct_and_non_direct_tables",
                {
                    "postgres.ph3.ph3_postgres_posthog_activitylog": _build_direct_table_type,
                    "raw.posthog_group": lambda _test_case: ast.TableType(
                        table=PostgresTable(name="raw.posthog_group", fields={}, postgres_table_name="posthog_group")
                    ),
                },
                False,
            ),
        ]
    )
    def test_should_use_direct_postgres(self, _name: str, table_factories, expected: bool):
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team)
        query_type = ast.SelectQueryType(
            tables={table_name: table_factory(self) for table_name, table_factory in table_factories.items()}
        )
        executor.select_query = ast.SelectQuery(type=query_type, select=[ast.Constant(value=1)])

        self.assertEqual(executor._should_use_direct_postgres(), expected)

    def test_should_use_direct_postgres_resolves_query_type_when_missing(self):
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
            name="ph3_postgres_without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT * FROM postgres.ph3.without_team_id",
            team=self.team,
        )

        executor._parse_query()
        executor._generate_hogql()

        self.assertIsNone(executor.select_query.type)
        self.assertEqual(executor._should_use_direct_postgres(), True)

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
            name="ph3_postgres_without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(
            query="SELECT * FROM without_team_id",
            team=self.team,
            selected_direct_source_id=str(source.id),
        )

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn("ph3.without_team_id", sql)
        self.assertNotIn(".team_id", sql)
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
            name="ph3_postgres_without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(query="SELECT * FROM postgres.ph3.without_team_id", team=self.team)

        with self.assertRaises(ExposedHogQLError) as error:
            executor.generate_clickhouse_sql()

        self.assertEqual(str(error.exception), "Direct Postgres queries require selecting a connection.")

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
            name="first_postgres_posthog_team",
            format="Parquet",
            team=self.team,
            external_data_source=first_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="second_postgres_posthog_team",
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
            selected_direct_source_id=str(second_source.id),
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
            selected_direct_source_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "Table not found in the selected connection.")

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
            name="ph3_postgres_posthog_dashboard",
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
            selected_direct_source_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertEqual(str(error.exception), "Unknown table `posthog_dashboard`.")

    def test_postgres_error_to_message_uses_primary_message(self):
        error = psycopg.errors.GroupingError(
            'column "posthog_dashboard.name" must appear in the GROUP BY clause or be used in an aggregate function'
        )
        self.assertEqual(
            postgres_error_to_message(error),
            'column "posthog_dashboard.name" must appear in the GROUP BY clause or be used in an aggregate function',
        )

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
            name="ph3_postgres_posthog_dashboard",
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
            selected_direct_source_id=str(source.id),
        )

        with self.assertRaises(ExposedHogQLError) as error:
            executor.execute()

        self.assertIn("must appear in the GROUP BY clause", str(error.exception))
        self.assertEqual(mock_connect.call_args.kwargs["options"], "-c default_transaction_read_only=on")
