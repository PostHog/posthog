from uuid import uuid4

from posthog.test.base import APIBaseTest

from posthog.hogql.query import HogQLQueryExecutor

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource

# Storage keys / URL pattern for direct-ClickHouse tables, duplicated as literals to respect the
# products.data_warehouse module boundary (the canonical constants live in
# products/data_warehouse/backend/direct_clickhouse.py).
DIRECT_CLICKHOUSE_URL_PATTERN = "direct://clickhouse"
DIRECT_CLICKHOUSE_DATABASE_OPTION = "direct_clickhouse_database"
DIRECT_CLICKHOUSE_TABLE_OPTION = "direct_clickhouse_table"


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

    def _create_table(
        self,
        source: ExternalDataSource,
        *,
        options: dict | None = None,
        enabled_columns: list[str] | None = None,
    ) -> DataWarehouseTable:
        table = DataWarehouseTable.objects.create(
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
        # The schema carries the column-picker restriction (enabled_columns); None means "all
        # columns", which is what gates the literal-star passthrough.
        ExternalDataSchema.objects.create(
            name="events", team=self.team, source=source, table=table, enabled_columns=enabled_columns
        )
        return table

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

    def test_select_star_stays_literal_for_direct_connection(self):
        # A top-level SELECT * on a direct ClickHouse table must print as a literal `*` so the
        # external server expands the star against its own live schema — not a HogQL-expanded column
        # list, which can include stale / materialized / alias columns that break the whole query
        # (ClickHouse error 47, UNKNOWN_IDENTIFIER).
        source = self._create_source(database="posthog")
        self._create_table(source)

        sql = self._from_database(source)
        # The pretty-printer puts the star on its own line (`SELECT\n    *\n`), so match on
        # "SELECT" followed only by whitespace before the `*` rather than the literal substring
        # "SELECT *" — a check that would otherwise never match either shape.
        self.assertRegex(sql, r"SELECT\s*\*\s")
        self.assertNotIn("events.id AS id", sql)
        self.assertNotIn("events.team_id AS team_id", sql)

    def test_select_star_expands_when_columns_are_restricted(self):
        # Security: with a column-picker restriction (enabled_columns) the table's fields are a
        # subset, so SELECT * must expand from them — a literal star would let the server expand
        # against the unrestricted physical table and leak the hidden columns.
        source = self._create_source(database="posthog")
        self._create_table(source, enabled_columns=["id"])

        sql = self._from_database(source)
        self.assertNotRegex(sql, r"SELECT\s*\*\s")
        self.assertIn("events.id AS id", sql)

    def test_explicit_columns_still_expand_for_direct_connection(self):
        # Only the star is kept literal — explicit column selection is unaffected.
        source = self._create_source(database="posthog")
        self._create_table(source)

        executor = HogQLQueryExecutor(query="SELECT id FROM events", team=self.team, connection_id=str(source.id))
        sql, _context = executor.generate_clickhouse_sql()
        self.assertIn("events.id AS id", sql.replace("`", ""))
        self.assertNotRegex(sql, r"SELECT\s*\*\s")

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
