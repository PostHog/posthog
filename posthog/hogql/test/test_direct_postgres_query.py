from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


class TestDirectPostgresQuery(APIBaseTest):
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
            name="postgres.ph3.ph3_postgres_without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(query="SELECT * FROM postgres.ph3.ph3_postgres_without_team_id", team=self.team)

        executor._parse_query()

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
            name="postgres.ph3.ph3_postgres_without_team_id",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        executor = HogQLQueryExecutor(query="SELECT * FROM postgres.ph3.ph3_postgres_without_team_id", team=self.team)

        sql, _context = executor.generate_clickhouse_sql()

        self.assertIn('FROM "ph3"."ph3_postgres_without_team_id"', sql)
        self.assertNotIn("team_id", sql)
        self.assertEqual(executor.direct_postgres_source_id, str(source.id))
