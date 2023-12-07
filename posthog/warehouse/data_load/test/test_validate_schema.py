from posthog.test.base import BaseTest, ClickhouseTestMixin
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource, DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
import uuid
from unittest.mock import patch


class TestValidateSchema(ClickhouseTestMixin, BaseTest):
    def _create_external_data_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

    def _create_external_data_job(self, source_id, status) -> ExternalDataJob:
        return ExternalDataJob.objects.create(
            pipeline_id=source_id,
            status=status,
            team_id=self.team.pk,
        )

    def _create_datawarehouse_credential(self):
        return DataWarehouseCredential.objects.create(
            team=self.team,
            access_key="test-key",
            access_secret="test-secret",
        )

    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_validate_schema(self, mock_get_columns):
        pass

    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_validate_schema_and_update_table_no_existing_table(self, mock_get_columns):
        source = self._create_external_data_source()
        job = self._create_external_data_job(source.pk, "Running")

        with self.settings(AIRBYTE_BUCKET_KEY="key", AIRBYTE_BUCKET_SECRET="secret"):
            validate_schema_and_update_table(
                run_id=job.pk,
                team_id=self.team.pk,
                schemas=["test_schema"],
            )

        self.assertEqual(DataWarehouseTable.objects.filter(external_data_source_id=source.pk).count(), 1)

    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_validate_schema_and_update_table_existing_table(self, mock_get_columns):
        source = self._create_external_data_source()
        old_job = self._create_external_data_job(source.pk, "Completed")
        job = self._create_external_data_job(source.pk, "Running")
        DataWarehouseTable.objects.create(
            credential=self._create_datawarehouse_credential(),
            name="test_table",
            format="Parquet",
            url_pattern=old_job.url_pattern_by_schema("test_schema"),
            team_id=self.team.pk,
            external_data_source_id=source.pk,
        )

        with self.settings(AIRBYTE_BUCKET_KEY="key", AIRBYTE_BUCKET_SECRET="secret"):
            validate_schema_and_update_table(
                run_id=job.pk,
                team_id=self.team.pk,
                schemas=["test_schema"],
            )

        tables = DataWarehouseTable.objects.filter(external_data_source_id=source.pk).all()
        self.assertEqual(len(tables), 1)
        # url got updated
        self.assertEqual(tables[0].url_pattern, job.url_pattern_by_schema("test_schema"))

    @patch(
        "posthog.warehouse.data_load.validate_schema.validate_schema",
    )
    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_validate_schema_and_update_table_half_broken(self, mock_get_columns, mock_validate):
        credential = self._create_datawarehouse_credential()
        mock_validate.side_effect = [
            Exception,
            {
                "credential": credential,
                "format": "Parquet",
                "name": "test_schema",
                "url_pattern": "test_url_pattern",
                "team_id": self.team.pk,
            },
        ]

        source = self._create_external_data_source()
        job = self._create_external_data_job(source.pk, "Running")

        with self.settings(AIRBYTE_BUCKET_KEY="test-key", AIRBYTE_BUCKET_SECRET="test-secret"):
            validate_schema_and_update_table(
                run_id=job.pk,
                team_id=self.team.pk,
                schemas=["broken_schema", "test_schema"],
            )

        self.assertEqual(DataWarehouseTable.objects.filter(external_data_source_id=source.pk).count(), 1)
