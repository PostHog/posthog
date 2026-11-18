import uuid

from posthog.test.base import APIBaseTest

from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable

from products.data_warehouse.backend.facade.sources import DIRECT_ESTIMATED_ROW_COUNT_OPTION
from products.data_warehouse.backend.snowflake_helpers import reconcile_snowflake_schemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class TestReconcileSnowflakeSchemasRowEstimate(APIBaseTest):
    def test_direct_table_keeps_the_catalog_row_estimate_for_the_planner(self) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Snowflake",
            created_by=self.user,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"account_id": "acct", "database": "DB", "schema": "PUBLIC", "warehouse": "WH"},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="orders", should_sync=True
        )

        def discovered(estimated_row_count: int | None) -> SourceSchema:
            return SourceSchema(
                name="orders",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "NUMBER", False)],
                source_catalog="DB",
                source_schema="PUBLIC",
                source_table_name="orders",
                estimated_row_count=estimated_row_count,
            )

        reconcile_snowflake_schemas(source=source, source_schemas=[discovered(812_000)], team_id=self.team.pk)

        schema.refresh_from_db()
        assert schema.table is not None
        assert schema.table.options[DIRECT_ESTIMATED_ROW_COUNT_OPTION] == 812_000
        definition = schema.table.hogql_definition()
        assert isinstance(definition, DirectSnowflakeTable)
        assert definition.estimated_row_count == 812_000

        # A refresh whose discovery could not read the catalog keeps the last figure rather than dropping it.
        reconcile_snowflake_schemas(source=source, source_schemas=[discovered(None)], team_id=self.team.pk)
        schema.table.refresh_from_db()
        assert schema.table.options[DIRECT_ESTIMATED_ROW_COUNT_OPTION] == 812_000
