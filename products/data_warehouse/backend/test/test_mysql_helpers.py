import uuid

from posthog.test.base import APIBaseTest

from posthog.hogql.database.direct_mysql_table import DirectMySQLTable

from products.data_warehouse.backend.facade.sources import DIRECT_ESTIMATED_ROW_COUNT_OPTION
from products.data_warehouse.backend.mysql_helpers import reconcile_mysql_schemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class TestReconcileMySQLSchemasRowEstimate(APIBaseTest):
    def test_direct_table_keeps_the_catalog_row_estimate_for_the_planner(self) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="MySQL",
            created_by=self.user,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 3306, "database": "app", "schema": "app"},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="orders", should_sync=True
        )

        reconcile_mysql_schemas(
            source=source,
            source_schemas=[
                SourceSchema(
                    name="orders",
                    supports_incremental=False,
                    supports_append=False,
                    columns=[("id", "int", False)],
                    source_schema="app",
                    source_table_name="orders",
                    estimated_row_count=812_000,
                )
            ],
            team_id=self.team.pk,
        )

        schema.refresh_from_db()
        assert schema.table is not None
        assert schema.table.options[DIRECT_ESTIMATED_ROW_COUNT_OPTION] == 812_000
        definition = schema.table.hogql_definition()
        assert isinstance(definition, DirectMySQLTable)
        assert definition.estimated_row_count == 812_000

        # A refresh whose discovery could not read the catalog keeps the last figure rather than dropping it.
        reconcile_mysql_schemas(
            source=source,
            source_schemas=[
                SourceSchema(
                    name="orders",
                    supports_incremental=False,
                    supports_append=False,
                    columns=[("id", "int", False)],
                    source_schema="app",
                    source_table_name="orders",
                )
            ],
            team_id=self.team.pk,
        )
        schema.table.refresh_from_db()
        assert schema.table.options[DIRECT_ESTIMATED_ROW_COUNT_OPTION] == 812_000
