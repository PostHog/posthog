from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

from parameterized import parameterized

from products.data_warehouse.backend.models.credential import DataWarehouseCredential as DataWarehouseCredentialModel
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource as ExternalDataSourceModel
from products.data_warehouse.backend.models.table import DataWarehouseTable as DataWarehouseTableModel

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class DeletingCredentialsMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0012_externaldatasource_description"
    migrate_to = "0013_credential_deletion"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "data_warehouse"

    def setUp(self):
        """Override to specify posthog migration state alongside data_warehouse migration"""
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        # Migrate from both data_warehouse 0012 AND posthog 0955 (which includes default_anonymize_ips)
        migrate_from = [
            ("data_warehouse", self.migrate_from),
            ("posthog", "0955_alter_organization_is_ai_data_processing_approved"),
        ]
        migrate_to = [("data_warehouse", self.migrate_to)]

        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps

        # Reverse to the original migration
        executor.migrate(migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload
        executor.migrate(migrate_to)

        self.apps = executor.loader.project_state(migrate_to).apps

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        DataWarehouseTable: DataWarehouseTableModel = apps.get_model("data_warehouse", "DataWarehouseTable")
        DataWarehouseCredential: DataWarehouseCredentialModel = apps.get_model(
            "data_warehouse", "DataWarehouseCredential"
        )
        ExternalDataSource: ExternalDataSourceModel = apps.get_model("data_warehouse", "ExternalDataSource")

        # At migration 0012, posthog migration 0955 has been applied (per dependency),
        # which means default_anonymize_ips field exists and needs to be set explicitly
        org = Organization.objects.create(name="Test Organization", default_anonymize_ips=False)
        proj = Project.objects.create(id=999999, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=proj, name="Test Team")

        self.DataWarehouseTable = DataWarehouseTable
        self.DataWarehouseCredential = DataWarehouseCredential
        self.ExternalDataSource = ExternalDataSource

        self.credentials = {}
        self.tables = {}
        self.sources = {}

        # Credential 1: Used by table with external_data_source_id (should be deleted)
        self.credentials["to_delete_1"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key1", access_secret="secret1"
        )

        # Credential 2: Used by table with external_data_source_id (should be deleted)
        self.credentials["to_delete_2"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key2", access_secret="secret2"
        )

        # Credential 3: Used by table WITHOUT external_data_source_id (should be kept)
        self.credentials["to_keep_1"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key3", access_secret="secret3"
        )

        # Credential 4: Orphaned credential not used by any table
        self.credentials["to_keep_2"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key4", access_secret="secret4"
        )

        # Credential 5: Not referenced by any table (should be kept)
        self.credentials["unused"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key5", access_secret="secret5"
        )

        # External data sources
        self.sources["source_1"] = ExternalDataSource.objects.create(
            team=team, source_id="src1", connection_id="conn1", status="Completed"
        )

        self.sources["source_2"] = ExternalDataSource.objects.create(
            team=team, source_id="src2", connection_id="conn2", status="Completed"
        )

        # Table 1: Has external_data_source_id AND credential_id (credential should be deleted, credential_id should be set to NULL)
        self.tables["with_source_and_cred_1"] = DataWarehouseTable.objects.create(
            team=team,
            name="table1",
            format="Parquet",
            url_pattern="s3://bucket/table1",
            external_data_source=self.sources["source_1"],
            credential=self.credentials["to_delete_1"],
        )

        # Table 2: Has external_data_source_id AND credential_id with different credential (credential should be deleted, credential_id should be set to NULL)
        self.tables["with_source_and_cred_2"] = DataWarehouseTable.objects.create(
            team=team,
            name="table2",
            format="Parquet",
            url_pattern="s3://bucket/table2",
            external_data_source=self.sources["source_2"],
            credential=self.credentials["to_delete_2"],
        )

        # Table 3: Has external_data_source_id but credential_id is NULL (nothing should change)
        self.tables["with_source_no_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="table3",
            format="Parquet",
            url_pattern="s3://bucket/table3",
            external_data_source=self.sources["source_1"],
            credential=None,
        )

        # Table 4: Has credential_id but NO external_data_source_id (credential should be kept, credential_id should remain)
        self.tables["no_source_with_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="table4",
            format="Parquet",
            url_pattern="s3://bucket/table4",
            external_data_source=None,
            credential=self.credentials["to_keep_1"],
        )

        # Table 5: Has neither external_data_source_id nor credential_id (nothing should change)
        self.tables["no_source_no_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="table5",
            format="Parquet",
            url_pattern="s3://bucket/table5",
            external_data_source=None,
            credential=None,
        )

        # Table 6: Multiple tables referencing same credential with external_data_source_id
        self.tables["duplicate_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="table6",
            format="Parquet",
            url_pattern="s3://bucket/table6",
            external_data_source=self.sources["source_2"],
            credential=self.credentials["to_delete_1"],  # Same as table1
        )

    @parameterized.expand(
        [
            ("with_source_and_cred_1", None),
            ("with_source_and_cred_2", None),
            ("duplicate_cred", None),
        ]
    )
    def test_tables_with_source_and_credential_have_credential_nulled(self, table_key, expected_credential):
        """Tables with both external_data_source_id and credential_id should have credential_id set to NULL"""
        table = self.DataWarehouseTable.objects.get(id=self.tables[table_key].id)
        self.assertEqual(table.credential_id, expected_credential)

    @parameterized.expand(
        [
            ("with_source_no_cred", None),
            ("no_source_no_cred", None),
        ]
    )
    def test_tables_without_credential_remain_unchanged(self, table_key, expected_credential):
        """Tables without credential_id should remain unchanged"""

        table = self.DataWarehouseTable.objects.get(id=self.tables[table_key].id)
        self.assertEqual(table.credential_id, expected_credential)

    def test_table_without_source_keeps_credential(self):
        """Tables without external_data_source_id should keep their credential_id"""

        table = self.DataWarehouseTable.objects.get(id=self.tables["no_source_with_cred"].id)
        self.assertEqual(table.credential_id, self.credentials["to_keep_1"].id)

    @parameterized.expand(
        [
            ("to_delete_1",),
            ("to_delete_2",),
        ]
    )
    def test_credentials_referenced_by_tables_with_source_are_deleted(self, credential_key):
        """Credentials referenced by tables with external_data_source_id should be deleted"""
        with self.assertRaises(self.DataWarehouseCredential.DoesNotExist):
            self.DataWarehouseCredential.objects.get(id=self.credentials[credential_key].id)

    @parameterized.expand(
        [
            ("to_keep_1",),
            ("to_keep_2",),
            ("unused",),
        ]
    )
    def test_credentials_not_referenced_or_without_source_are_kept(self, credential_key):
        """Credentials not referenced by tables with external_data_source_id should be kept"""
        credential = self.DataWarehouseCredential.objects.get(id=self.credentials[credential_key].id)
        self.assertIsNotNone(credential)

    def test_all_table_counts(self):
        """Verify all tables still exist after migration"""
        self.assertEqual(self.DataWarehouseTable.objects.count(), 6)

    def test_credential_counts(self):
        """Verify correct number of credentials deleted"""
        # Started with 5 credentials, 2 should be deleted (to_delete_1 and to_delete_2)
        self.assertEqual(self.DataWarehouseCredential.objects.count(), 3)
