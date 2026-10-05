import uuid

from posthog.test.base import APIBaseTest

from products.data_warehouse.backend.mysql_helpers import reconcile_mysql_schemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class TestReconcileMySQLSchemas(APIBaseTest):
    def test_direct_query_keeps_bare_row_matched_by_qualified_discovered_name(self) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="MySQL",
            created_by=self.user,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 3306, "database": "app_db", "schema": "app_db"},
        )
        users = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="users", should_sync=True
        )
        orders = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="orders", should_sync=True
        )

        source_schemas = [
            SourceSchema(
                name="app_db.users",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "int", False)],
                source_schema="app_db",
                source_table_name="users",
            ),
        ]

        stale_names = reconcile_mysql_schemas(source=source, source_schemas=source_schemas, team_id=self.team.pk)

        assert stale_names == ["orders"]
        users.refresh_from_db()
        orders.refresh_from_db()
        assert users.deleted is False
        assert users.table is not None
        assert users.table.deleted is False
        assert orders.deleted is True
