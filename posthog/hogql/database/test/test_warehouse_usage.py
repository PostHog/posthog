from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.warehouse_usage import extract_warehouse_sources
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import clone_expr

from products.warehouse_sources.backend.models import DataWarehouseCredential, DataWarehouseTable
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWarehouseUsage(BaseTest):
    def _create_stripe_table(self, name: str = "stripe_table_1") -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"source_id_{name}",
            connection_id=f"connection_id_{name}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        warehouse_table = DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name=name,
            source=source,
            table=warehouse_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )
        return source

    def _create_self_managed_table(self, name: str = "self_managed_1") -> None:
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/self/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def _sources_for(self, query: str):
        database = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, team=self.team, database=database, enable_select_queries=True)
        resolved = resolve_types(clone_expr(parse_select(query), True), context, dialect="hogql")
        return extract_warehouse_sources(resolved.type)

    def test_detects_connector_synced_source(self):
        source = self._create_stripe_table()

        sources = self._sources_for("SELECT id FROM stripe_table_1")

        assert len(sources) == 1
        assert sources[0].id == str(source.id)
        assert sources[0].source_type == "Stripe"

    def test_events_only_query_has_no_sources(self):
        self._create_stripe_table()

        assert self._sources_for("SELECT event FROM events") == []

    def test_self_managed_table_is_not_a_source(self):
        self._create_self_managed_table()

        # Self-managed S3 tables have no ExternalDataSource, so they are not counted.
        assert self._sources_for("SELECT id FROM self_managed_1") == []

    def test_join_of_events_and_warehouse_table_returns_only_the_source(self):
        source = self._create_stripe_table()

        sources = self._sources_for("SELECT e.event FROM events e LEFT JOIN stripe_table_1 s ON e.distinct_id = s.id")

        assert [s.id for s in sources] == [str(source.id)]

    def test_cte_named_like_a_table_is_not_a_source(self):
        self._create_stripe_table()

        # A CTE aliased to a warehouse-looking name must not be mistaken for the real table.
        sources = self._sources_for(
            "WITH stripe_table_1 AS (SELECT event FROM events) SELECT event FROM stripe_table_1"
        )

        assert sources == []

    def test_deduplicates_by_source(self):
        source = self._create_stripe_table()

        sources = self._sources_for("SELECT a.id FROM stripe_table_1 a JOIN stripe_table_1 b ON a.id = b.id")

        assert [s.id for s in sources] == [str(source.id)]
