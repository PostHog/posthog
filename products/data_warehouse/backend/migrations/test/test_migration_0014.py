from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

from parameterized import parameterized

from products.data_warehouse.backend.models.credential import DataWarehouseCredential as DataWarehouseCredentialModel
from products.data_warehouse.backend.models.datawarehouse_saved_query import (
    DataWarehouseSavedQuery as DataWarehouseSavedQueryModel,
)
from products.data_warehouse.backend.models.table import DataWarehouseTable as DataWarehouseTableModel

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class MatViewCredentialDeletionMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0013_credential_deletion"
    migrate_to = "0014_mat_view_credential_deletion"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "data_warehouse"

    def setUp(self):
        """Override to specify posthog migration state alongside data_warehouse migration"""
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        migrate_from = [
            ("data_warehouse", self.migrate_from),
            ("posthog", "0955_alter_organization_is_ai_data_processing_approved"),
        ]
        migrate_to = [("data_warehouse", self.migrate_to)]

        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps

        executor.migrate(migrate_from)

        self.setUpBeforeMigration(old_apps)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
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
        DataWarehouseSavedQuery: DataWarehouseSavedQueryModel = apps.get_model(
            "data_warehouse", "DataWarehouseSavedQuery"
        )

        org = Organization.objects.create(name="Test Organization", default_anonymize_ips=False)
        proj = Project.objects.create(id=999999, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=proj, name="Test Team")

        self.DataWarehouseTable = DataWarehouseTable
        self.DataWarehouseCredential = DataWarehouseCredential
        self.DataWarehouseSavedQuery = DataWarehouseSavedQuery

        self.credentials = {}
        self.tables = {}
        self.saved_queries = {}

        # Credential 1: Used by table that is materialized view (should be nulled)
        self.credentials["mat_view_cred"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key1", access_secret="secret1"
        )

        # Credential 2: Used by table that is materialized view (should be nulled)
        self.credentials["mat_view_cred_2"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key2", access_secret="secret2"
        )

        # Credential 3: Used by regular table (should be kept)
        self.credentials["regular_table_cred"] = DataWarehouseCredential.objects.create(
            team=team, access_key="key3", access_secret="secret3"
        )

        # Table 1: Has credential and is referenced by a saved query (credential should be nulled)
        self.tables["materialized_with_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="materialized_table_1",
            format="Parquet",
            url_pattern="s3://bucket/mat_table1",
            credential=self.credentials["mat_view_cred"],
        )

        # Table 2: Has credential and is referenced by a saved query (credential should be nulled)
        self.tables["materialized_with_cred_2"] = DataWarehouseTable.objects.create(
            team=team,
            name="materialized_table_2",
            format="Parquet",
            url_pattern="s3://bucket/mat_table2",
            credential=self.credentials["mat_view_cred_2"],
        )

        # Table 3: Has credential but NOT referenced by saved query (credential should remain)
        self.tables["regular_with_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="regular_table",
            format="Parquet",
            url_pattern="s3://bucket/regular_table",
            credential=self.credentials["regular_table_cred"],
        )

        # Table 4: No credential and is referenced by saved query (nothing should change)
        self.tables["materialized_no_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="materialized_table_3",
            format="Parquet",
            url_pattern="s3://bucket/mat_table3",
            credential=None,
        )

        # Table 5: No credential and NOT referenced by saved query (nothing should change)
        self.tables["regular_no_cred"] = DataWarehouseTable.objects.create(
            team=team,
            name="regular_table_2",
            format="Parquet",
            url_pattern="s3://bucket/regular_table2",
            credential=None,
        )

        # Saved queries (materialized views) referencing tables
        self.saved_queries["mat_view_1"] = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="materialized_view_1",
            query={"query": "SELECT * FROM materialized_table_1"},
            table=self.tables["materialized_with_cred"],
        )

        self.saved_queries["mat_view_2"] = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="materialized_view_2",
            query={"query": "SELECT * FROM materialized_table_2"},
            table=self.tables["materialized_with_cred_2"],
        )

        self.saved_queries["mat_view_3"] = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="materialized_view_3",
            query={"query": "SELECT * FROM materialized_table_3"},
            table=self.tables["materialized_no_cred"],
        )

    @parameterized.expand(
        [
            ("materialized_with_cred", None),
            ("materialized_with_cred_2", None),
            ("materialized_no_cred", None),
        ]
    )
    def test_materialized_view_tables_have_credential_nulled(self, table_key, expected_credential):
        """Tables referenced by saved queries should have credential_id set to NULL"""
        table = self.DataWarehouseTable.objects.get(id=self.tables[table_key].id)
        self.assertEqual(table.credential_id, expected_credential)

    @parameterized.expand(
        [
            ("regular_with_cred", "regular_table_cred"),
            ("regular_no_cred", None),
        ]
    )
    def test_non_materialized_tables_remain_unchanged(self, table_key, credential_key):
        """Tables not referenced by saved queries should keep their credentials"""
        table = self.DataWarehouseTable.objects.get(id=self.tables[table_key].id)
        expected_credential_id = self.credentials[credential_key].id if credential_key else None
        self.assertEqual(table.credential_id, expected_credential_id)

    def test_all_credentials_still_exist(self):
        """All credentials should still exist after migration"""
        self.assertEqual(self.DataWarehouseCredential.objects.count(), 3)

    def test_all_tables_still_exist(self):
        """All tables should still exist after migration"""
        self.assertEqual(self.DataWarehouseTable.objects.count(), 5)

    def test_all_saved_queries_still_exist(self):
        """All saved queries should still exist after migration"""
        self.assertEqual(self.DataWarehouseSavedQuery.objects.count(), 3)
