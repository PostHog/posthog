from posthog.test.base import BaseTest
from unittest.mock import patch

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

CLEANUP_PATH = "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.cleanup_cdc_resources_on_deletion"


class TestExternalDataSourceSoftDelete(BaseTest):
    """Soft-deletion marks the row deleted and unconditionally hands off to the
    registered source impl's `cleanup_cdc_resources_on_deletion` — each source
    decides whether there's anything to tear down. The model carries no
    source-specific knowledge."""

    def _create_source(self, *, source_type: str, job_inputs: dict | None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            source_id="src-1",
            connection_id="conn-1",
            destination_id="dest-1",
            team=self.team,
            status="Completed",
            source_type=source_type,
            job_inputs=job_inputs,
        )

    @patch(CLEANUP_PATH)
    def test_soft_delete_marks_deleted_and_delegates_to_source_impl(self, mock_cleanup):
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": True},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        self.assertIsNotNone(source.deleted_at)
        mock_cleanup.assert_called_once()
        ((called_source,), _) = mock_cleanup.call_args
        self.assertEqual(called_source.pk, source.pk)

    @patch(CLEANUP_PATH)
    def test_soft_delete_calls_cleanup_for_non_cdc_postgres_too(self, mock_cleanup):
        # Reviewer's design: model doesn't gate on cdc_enabled. The source impl is
        # responsible for deciding it has nothing to do.
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": False},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        mock_cleanup.assert_called_once()

    @patch(CLEANUP_PATH)
    def test_soft_delete_calls_cleanup_when_job_inputs_missing(self, mock_cleanup):
        source = self._create_source(source_type=ExternalDataSourceType.POSTGRES, job_inputs=None)

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        mock_cleanup.assert_called_once()

    @patch(CLEANUP_PATH)
    def test_soft_delete_cascades_to_tables_schemas_and_joins(self, _mock_cleanup):
        source = self._create_source(source_type=ExternalDataSourceType.POSTGRES, job_inputs={"host": "localhost"})
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        table = DataWarehouseTable.objects.create(
            name="pull_requests",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            credential=credential,
            url_pattern="s3://bucket/*",
        )
        schema = ExternalDataSchema.objects.create(name="pull_requests", team=self.team, source=source, table=table)
        join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="pull_requests",
            source_table_key="id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person",
        )
        # Control: an unrelated source's table/join must be untouched by the cascade.
        other_source = self._create_source(source_type=ExternalDataSourceType.POSTGRES, job_inputs=None)
        other_table = DataWarehouseTable.objects.create(
            name="customers",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=other_source,
            credential=credential,
            url_pattern="s3://bucket/customers/*",
        )
        other_join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="customers",
            source_table_key="id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person",
        )

        source.soft_delete()

        for obj in (source, table, schema, join):
            obj.refresh_from_db()
            self.assertTrue(obj.deleted, f"{type(obj).__name__} should be soft-deleted")

        other_table.refresh_from_db()
        other_join.refresh_from_db()
        self.assertFalse(other_table.deleted)
        self.assertFalse(other_join.deleted)
