import uuid

from posthog.test.base import APIBaseTest

from parameterized import parameterized

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

    @parameterized.expand(
        [
            ("catalog_gone", frozenset(), True),
            ("catalog_unreadable", frozenset({"ext_db__lake"}), False),
        ]
    )
    def test_external_catalog_table_is_removed_only_when_its_catalog_was_read(
        self, _name: str, retained_catalogs: frozenset[str], expect_removed: bool
    ) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.TRINO,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            job_inputs={"catalog": "hive"},
        )
        name = "ext_db__lake.billing.invoices"
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name=name, should_sync=True)
        reconcile_trino_schemas(
            source=source,
            source_schemas=[
                SourceSchema(
                    name=name,
                    supports_incremental=False,
                    supports_append=False,
                    columns=[("id", "bigint", False)],
                    source_catalog="ext_db__lake",
                    source_schema="billing",
                    source_table_name="invoices",
                )
            ],
            team_id=self.team.id,
        )
        schema.refresh_from_db()
        assert schema.table is not None
        assert schema.table.name == name
        assert schema.table.options["direct_trino_catalog"] == "ext_db__lake"

        stale = reconcile_trino_schemas(
            source=source, source_schemas=[], team_id=self.team.id, retained_catalogs=retained_catalogs
        )

        schema.refresh_from_db()
        assert stale == ([name] if expect_removed else [])
        assert schema.deleted is expect_removed
        assert schema.table.deleted is expect_removed
