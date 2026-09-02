from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import execute_hogql_query

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

COLUMNS = {
    "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
    "email": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
}


class TestDirectConnectionInformationSchema(ClickhouseTestMixin, APIBaseTest):
    def _create_direct_source(self, *, table_names: list[str]) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="shop",
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            },
        )
        for name in table_names:
            DataWarehouseTable.objects.create(
                name=name,
                format="Parquet",
                team=self.team,
                external_data_source=source,
                url_pattern="",
                columns=COLUMNS,
            )
        return source

    def test_connection_catalog_lists_only_its_own_tables(self):
        # Without this the only way to learn a connection's table names is to already know them: the
        # connection's tables are absent from the default catalog by design, and the default catalog's
        # tables must not leak into the connection's.
        source = self._create_direct_source(table_names=["orders", "customers"])

        response = execute_hogql_query(
            "SELECT table_name FROM system.information_schema.tables",
            team=self.team,
            connection_id=str(source.id),
        )

        names = {row[0] for row in response.results or []}
        assert {"orders", "customers"}.issubset(names)
        assert "events" not in names
        assert "persons" not in names

    def test_connection_catalog_reports_columns(self):
        source = self._create_direct_source(table_names=["orders"])

        response = execute_hogql_query(
            "SELECT column_name, data_type FROM system.information_schema.columns WHERE table_name = 'orders'",
            team=self.team,
            connection_id=str(source.id),
        )

        assert {(row[0], row[1]) for row in response.results or []} == {("id", "Integer"), ("email", "String")}

    def test_catalog_query_runs_on_clickhouse_not_the_remote_engine(self):
        # The rows are built in Python and shipped as ClickHouse external data. Translating the query
        # into the remote engine's dialect would send it a table that only exists inside PostHog.
        source = self._create_direct_source(table_names=["orders"])

        response = execute_hogql_query(
            "SELECT table_name FROM system.information_schema.tables",
            team=self.team,
            connection_id=str(source.id),
        )

        assert response.clickhouse is not None
        assert "__ph_information_schema_tables_" in response.clickhouse

    def test_joining_the_catalog_to_a_connection_table_is_rejected(self):
        # One half would have to run on ClickHouse and the other on the remote engine.
        source = self._create_direct_source(table_names=["orders"])

        with self.assertRaises(ExposedHogQLError) as error:
            execute_hogql_query(
                "SELECT t.table_name FROM system.information_schema.tables AS t, orders",
                team=self.team,
                connection_id=str(source.id),
            )

        assert "cannot be joined with the information schema" in str(error.exception)

    @parameterized.expand(
        [
            ("metrics",),
            ("certifications",),
            ("relationship_proposals",),
            ("relationships",),
        ]
    )
    def test_team_catalog_only_tables_are_absent_from_a_connection(self, table: str):
        # These describe the team's own ClickHouse catalog. Answering them here would report the team's
        # state under a name that reads as the connection's.
        source = self._create_direct_source(table_names=["orders"])

        with self.assertRaises(Exception) as error:
            execute_hogql_query(
                f"SELECT * FROM system.information_schema.{table}",
                team=self.team,
                connection_id=str(source.id),
            )

        assert "Unknown table" in str(error.exception)

    def test_default_catalog_keeps_the_full_information_schema(self):
        # The connection catalog mounts a trimmed `system` node; the default catalog must be untouched.
        database = Database.create_for(team=self.team)

        names = database.get_system_table_names()

        for table in ["tables", "columns", "relationships", "data_types"]:
            assert f"system.information_schema.{table}" in names
