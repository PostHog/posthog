from typing import Any

from freezegun import freeze_time
from posthog.test.base import NonAtomicTestMigrations

from products.data_warehouse.backend.models import (
    DataWarehouseTable as DataWarehouseTableModel,
    ExternalDataSchema as ExternalDataSchemaModel,
    ExternalDataSource as ExternalDataSourceModel,
)

# maps case name to a tuple (sync_type_config, deleted)
TEST_CASES = {
    "deleted": ({}, True),
    "disabled_partitioning": (
        {
            "partitioning_enabled": False,
            "partition_mode": None,
            "partition_format": None,
        },
        False,
    ),
    "md5_partitioning": (
        {
            "partitioning_enabled": True,
            "partition_mode": "md5",
            "partition_format": None,
        },
        False,
    ),
    "numerical_partitioning": (
        {
            "partitioning_enabled": True,
            "partition_mode": "numerical",
            "partition_format": None,
        },
        False,
    ),
    "month_partitioning": (
        {
            "partitioning_enabled": True,
            "partition_mode": "datetime",
            "partition_format": "month",
        },
        False,
    ),
    "day_partitioning": (
        {
            "partitioning_enabled": True,
            "partition_mode": "datetime",
            "partition_format": "day",
        },
        False,
    ),
    "affected_set": (
        {
            "partitioning_enabled": True,
            "partition_mode": "datetime",
        },
        False,
    ),
}


class BackfillWeekPartitions(NonAtomicTestMigrations):
    migrate_from = "0002_cleanup_datawarehouse_contenttypes"
    migrate_to = "0003_backfill_partition_format"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        ExternalDataSource: ExternalDataSourceModel = apps.get_model("data_warehouse", "ExternalDataSource")
        ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("data_warehouse", "ExternalDataSchema")
        DataWarehouseTable: DataWarehouseTableModel = apps.get_model("data_warehouse", "DataWarehouseTable")

        # Use raw SQL to create organization - at this migration state (0002),
        # the Organization historical model doesn't have default_anonymize_ips field yet,
        # but the database table does (migration framework doesn't roll back schema)
        from django.db import connection

        from posthog.models import UUIDT

        org_id = UUIDT()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_organization
                (id, name, slug, created_at, updated_at, plugins_access_level,
                 for_internal_metrics, is_member_join_email_enabled, default_anonymize_ips)
                VALUES (%s, %s, '', NOW(), NOW(), 9, FALSE, TRUE, FALSE)
                """,
                [org_id, "o1"],
            )
        self.organization = Organization.objects.get(id=org_id)
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)

        # mapping from test case name to schemata
        self.cases: dict[str, Any] = {
            "Stripe": [],
            "TemporalIO": [],
            "GoogleAds": [],
        }
        with freeze_time("2025-01-01T12:00:00.000Z"):
            for source_type in self.cases:
                source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)
                table = DataWarehouseTable.objects.create(
                    team=self.team, name="table", external_data_source_id=source.id
                )
                for name, (config, deleted) in TEST_CASES.items():
                    schema = ExternalDataSchema.objects.create(
                        team=self.team, table=table, source_id=source.id, deleted=deleted, sync_type_config=config
                    )
                    self.cases[source_type].append((name, schema))

    def test_migration(self):
        ExternalDataSchema = self.apps.get_model("data_warehouse", "ExternalDataSchema")  # type: ignore

        for source_type in self.cases:
            for name, old_schema in self.cases[source_type]:
                schema = ExternalDataSchema.objects.get(id=old_schema.id)
                # partition format should remain null for all of these case regardless of source type
                if name in ("deleted", "disabled_partitioning", "md5_partitioning", "numerical_partitioning"):
                    assert schema.sync_type_config.get("partition_format") is None, f"{source_type} {name}"
                # month partitioning should remain month partitioning regardless of source type
                if name == "month_partitioning":
                    assert schema.sync_type_config.get("partition_format") == "month", f"{source_type} {name}"
                # day partitioning should remain day partitioning regardless of source type
                if name == "day_partitioning":
                    assert schema.sync_type_config.get("partition_format") == "day", f"{source_type} {name}"
                # GoogleAds and TemporalIO should be backfilled to day, all others should be backfilled to month
                if name == "affected_set":
                    if source_type in ("TemporalIO", "GoogleAds"):
                        assert schema.sync_type_config.get("partition_format") == "day", f"{source_type} {name}"
                    else:
                        assert schema.sync_type_config.get("partition_format") == "month", f"{source_type} {name}"
