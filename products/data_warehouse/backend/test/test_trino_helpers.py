import uuid

from posthog.test.base import APIBaseTest

from products.data_warehouse.backend.trino_helpers import reconcile_trino_schemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestReconcileTrinoSchemas(APIBaseTest):
    def test_prunes_columns_that_are_no_longer_available(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.TRINO,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"catalog": "hive"},
        )
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="analytics.events",
            should_sync=False,
            enabled_columns=["id", "removed"],
        )

        stale = reconcile_trino_schemas(
            source=source,
            source_schemas=[
                SourceSchema(
                    name="analytics.events",
                    supports_incremental=False,
                    supports_append=False,
                    columns=[("id", "bigint", False)],
                    source_catalog="hive",
                    source_schema="analytics",
                    source_table_name="events",
                )
            ],
            team_id=self.team.id,
        )

        schema.refresh_from_db()
        assert stale == []
        assert schema.enabled_columns == ["id"]
