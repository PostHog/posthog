from uuid import uuid4

from posthog.test.base import APIBaseTest

from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.direct_clickhouse import (
    DIRECT_CLICKHOUSE_DATABASE_OPTION,
    DIRECT_CLICKHOUSE_TABLE_OPTION,
    DIRECT_CLICKHOUSE_URL_PATTERN,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestDirectClickHouseQuery(APIBaseTest):
    def _create_source(self, *, database: str) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="ClickHouse",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ch",
            job_inputs={
                "host": "localhost",
                "port": 8443,
                "database": database,
                "user": "readonly_direct_connect",
                "password": "password",
            },
        )

    def _create_table(self, source: ExternalDataSource, *, options: dict | None = None) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern=DIRECT_CLICKHOUSE_URL_PATTERN,
            # A team_id column is present so the query compiles — the ClickHouse printer's team_id
            # guard on direct tables is a separate concern and not what this test exercises.
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "team_id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
            options=options or {},
        )

    def _from_database(self, source: ExternalDataSource) -> str:
        executor = HogQLQueryExecutor(query="SELECT * FROM events", team=self.team, connection_id=str(source.id))
        sql, _context = executor.generate_clickhouse_sql()
        # Normalize away identifier backticks so the assertion is agnostic to escaping.
        return sql.replace("`", "")

    def test_uses_the_sources_configured_database(self):
        source = self._create_source(database="posthog")
        self._create_table(source)

        sql = self._from_database(source)
        self.assertIn("posthog.events", sql)

    def test_configured_database_overrides_a_stale_default_option(self):
        # Regression: a table synced before the source's database was set stored "default" in its
        # per-table options. The live config ("posthog") must win, else the query targets
        # default.events and the server returns UNKNOWN_DATABASE.
        source = self._create_source(database="posthog")
        self._create_table(
            source,
            options={DIRECT_CLICKHOUSE_DATABASE_OPTION: "default", DIRECT_CLICKHOUSE_TABLE_OPTION: "events"},
        )

        sql = self._from_database(source)
        self.assertIn("posthog.events", sql)
        self.assertNotIn("default.events", sql)

    def test_falls_back_to_stored_option_when_no_database_configured(self):
        # When the source has no configured database, the per-table option is the only signal.
        source = self._create_source(database="")
        self._create_table(
            source,
            options={DIRECT_CLICKHOUSE_DATABASE_OPTION: "analytics", DIRECT_CLICKHOUSE_TABLE_OPTION: "events"},
        )

        sql = self._from_database(source)
        self.assertIn("analytics.events", sql)
