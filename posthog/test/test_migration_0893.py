from typing import Any

from freezegun import freeze_time
from posthog.test.base import NonAtomicTestMigrations

from posthog.warehouse.models import (
    DataWarehouseTable as DataWarehouseTableModel,
    ExternalDataSchema as ExternalDataSchemaModel,
    ExternalDataSource as ExternalDataSourceModel,
)

SYNC_TYPE_PARTITIONING_DISABLED = {
    "partitioning_enabled": False,
    "partition_mode": None,
    "partition_format": None,
}
SYNC_TYPE_PARTITIONING_MD5 = {
    "partitioning_enabled": True,
    "partition_mode": "md5",
    "partition_format": None,
}
SYNC_TYPE_PARTITIONING_NUMERICAL = {
    "partitioning_enabled": True,
    "partition_mode": "numerical",
    "partition_format": None,
}
SYNC_TYPE_PARTITIONING_DAY = {
    "partitioning_enabled": True,
    "partition_mode": "datetime",
    "partition_format": "day",
}
SYNC_TYPE_PARTITIONING_MONTH = {
    "partitioning_enabled": True,
    "partition_mode": "datetime",
    "partition_format": "month",
}
SYNC_TYPE_AFFECTED_SET = {
    "partitioning_enabled": True,
    "partition_mode": "datetime",
    "partition_format": None,
}


class BackfillWeekPartitions(NonAtomicTestMigrations):
    migrate_from = "0892_alter_integration_kind"
    migrate_to = "0893_backfill_partition_format"

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

            self.table_1 = DataWarehouseTable.objects.create(
                team=self.team, name="table_a", external_data_source_id=source_1.id
            )

            # tests that deleted tables are ignored
            self.schema_1 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                deleted=True,
            )
            # tests that sync configs with partitioning disabled are ignored
            self.schema_2 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_DISABLED,
            )
            # tests that sync configs with md5 partitions are ignored
            self.schema_3 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_MD5,
            )
            # tests that sync configs with numerical partitions are ignored
            self.schema_4 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_NUMERICAL,
            )
            # tests that sync configs with partition format = "day" are ignored
            self.schema_5 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_DAY,
            )
            # tests that sync configs with partition format = "month" are ignored
            self.schema_6 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_MONTH,
            )
            # tests that sync configs which match our target set have partition format set to "week"
            self.schema_7 = ExternalDataSchema.objects.create(
                team=self.team,
                table=self.table_1,
                source_id=source_1.id,
                sync_type_config=SYNC_TYPE_PARTITIONING_MONTH,
            )

    def test_migration(self):
        # schema 1: deleted sync
        assert self.schema_1.sync_type_config.get("partition_format") is None

        # schema 2: disabled partitioning
        assert self.schema_2.sync_type_config.get("partition_format") is None

        # schema 3: md5 partitioning
        assert self.schema_3.sync_type_config.get("partition_format") is None

        # schema 4: numerical partitioning
        assert self.schema_4.sync_type_config.get("partition_format") is None

        # schema 5: day partitioning
        assert self.schema_5.sync_type_config.get("partition_format") == "day"

        # schema 6: month partitioning
        assert self.schema_6.sync_type_config.get("partition_format") == "month"

        # schema 7: affected set backfilled to "month"
        assert self.schema_7.sync_type_config.get("partition_format") == "month"
