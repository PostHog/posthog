from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import NonAtomicTestMigrations

from products.data_warehouse.backend.models import (
    DataWarehouseTable as DataWarehouseTableModel,
    ExternalDataSchema as ExternalDataSchemaModel,
    ExternalDataSource as ExternalDataSourceModel,
)


class DuplicateWarehouseTables(NonAtomicTestMigrations):
    migrate_from = "0848_activitylog_detail_gin_index"
    migrate_to = "0849_duplicate_warehouse_tables"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        ExternalDataSource: ExternalDataSourceModel = apps.get_model("posthog", "ExternalDataSource")
        ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("posthog", "ExternalDataSchema")
        DataWarehouseTable: DataWarehouseTableModel = apps.get_model("posthog", "DataWarehouseTable")

        self.organization = Organization.objects.create(name="o1")
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)

        with freeze_time("2025-01-01T12:00:00.000Z"):
            source_1 = ExternalDataSource.objects.create(team=self.team, source_type="Stripe")
            source_2 = ExternalDataSource.objects.create(team=self.team, source_type="Stripe")
            source_3 = ExternalDataSource.objects.create(team=self.team, source_type="Stripe")

            self.table_1 = DataWarehouseTable.objects.create(
                team=self.team, name="table_a", external_data_source_id=source_1.id
            )
            self.table_2 = DataWarehouseTable.objects.create(
                team=self.team, name="table_a", external_data_source_id=source_1.id
            )
            self.table_3 = DataWarehouseTable.objects.create(
                team=self.team, name="table_a", external_data_source_id=source_1.id
            )
            self.schema_1 = ExternalDataSchema.objects.create(team=self.team, table=self.table_1, source_id=source_1.id)

            self.table_4 = DataWarehouseTable.objects.create(
                team=self.team, name="table_b", external_data_source_id=source_2.id
            )
            self.schema_2 = ExternalDataSchema.objects.create(team=self.team, table=self.table_4, source_id=source_2.id)

            self.table_5 = DataWarehouseTable.objects.create(
                team=self.team,
                name="table_c",
                external_data_source_id=source_3.id,
                deleted=True,
                deleted_at=datetime.now(),
            )
            self.table_6 = DataWarehouseTable.objects.create(
                team=self.team, name="table_c", external_data_source_id=source_3.id
            )
            self.schema_3 = ExternalDataSchema.objects.create(team=self.team, table=self.table_6, source_id=source_3.id)

    def test_migration(self):
        self.table_1.refresh_from_db()
        self.table_2.refresh_from_db()
        self.table_3.refresh_from_db()
        self.table_4.refresh_from_db()
        self.table_5.refresh_from_db()
        self.table_6.refresh_from_db()

        # Schema 1
        assert self.table_1.deleted is False
        assert self.table_1.deleted_at is None
        assert self.table_2.deleted is True
        assert self.table_2.deleted_at is not None
        assert self.table_3.deleted is True
        assert self.table_3.deleted_at is not None

        # Schema 2
        assert self.table_4.deleted is False
        assert self.table_4.deleted_at is None

        # Schema 3
        assert self.table_5.deleted is True
        assert self.table_5.deleted_at == datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        assert self.table_6.deleted is False
        assert self.table_6.deleted_at is None
