from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


class TestDirectPostgresQuery(APIBaseTest):
    @parameterized.expand(
        [
            (
                "unaliased_table",
                ast.TableType(
                    table=DirectPostgresTable(
                        name="postgres.ph3.ph3_postgres_posthog_activitylog",
                        fields={},
                        postgres_schema="ph3",
                        postgres_table_name="ph3_postgres_posthog_activitylog",
                        external_data_source_id="source-id",
                    )
                ),
            ),
            (
                "aliased_table",
                ast.TableAliasType(
                    alias="activitylog",
                    table_type=ast.TableType(
                        table=DirectPostgresTable(
                            name="postgres.ph3.ph3_postgres_posthog_activitylog",
                            fields={},
                            postgres_schema="ph3",
                            postgres_table_name="ph3_postgres_posthog_activitylog",
                            external_data_source_id="source-id",
                        )
                    ),
                ),
            ),
        ]
    )
    def test_extract_direct_postgres_source_ids(self, _name: str, table_type: ast.TableType | ast.TableAliasType):
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team)
        query_type = ast.SelectQueryType(tables={"postgres.ph3.ph3_postgres_posthog_activitylog": table_type})

        source_ids = executor._extract_direct_postgres_sources_from_type(query_type)

        self.assertEqual(source_ids, {"source-id"})

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
