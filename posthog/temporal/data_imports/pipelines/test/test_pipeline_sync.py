import functools
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch
import uuid

import boto3
import pytest
import structlog
from django.conf import settings
from django.test import override_settings
from posthog.temporal.data_imports.pipelines.pipeline_sync import DataImportPipelineSync, PipelineInputs
from posthog.temporal.data_imports.pipelines.stripe import stripe_source
from posthog.test.base import APIBaseTest
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource


BUCKET_NAME = "test-pipeline-sync"
SESSION = boto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


class TestDataImportPipeline(APIBaseTest):
    @pytest.fixture(autouse=True)
    def minio_client(self):
        """Manage an S3 client to interact with a MinIO bucket.

        Yields the client after creating a bucket. Upon resuming, we delete
        the contents and the bucket itself.
        """
        minio_client = create_test_client(
            "s3",
            aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )

        try:
            minio_client.head_bucket(Bucket=BUCKET_NAME)
        except:
            minio_client.create_bucket(Bucket=BUCKET_NAME)

        yield minio_client

    def _create_pipeline(self, schema_name: str, incremental: bool):
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="running",
            source_type="Stripe",
        )
        schema = ExternalDataSchema.objects.create(
            name=schema_name,
            team_id=self.team.pk,
            source_id=source.pk,
            source=source,
        )
        job = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.pk,
            pipeline=source,
            schema_id=schema.pk,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=str(uuid.uuid4()),
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        pipeline = DataImportPipelineSync(
            inputs=PipelineInputs(
                source_id=source.pk,
                run_id=str(job.pk),
                schema_id=schema.pk,
                dataset_name=job.folder_path(),
                job_type=ExternalDataSource.Type.STRIPE,
                team_id=self.team.pk,
            ),
            source=stripe_source(
                api_key="",
                account_id="",
                endpoint=schema_name,
                is_incremental=incremental,
                team_id=self.team.pk,
                job_id=str(job.pk),
                db_incremental_field_last_value=0,
            ),
            logger=structlog.get_logger(),
            incremental=incremental,
            reset_pipeline=False,
        )

        return pipeline

    @pytest.mark.django_db(transaction=True)
    def test_pipeline_non_incremental(self):
        def mock_create_pipeline(local_self: Any):
            mock = MagicMock()
            mock.last_trace.last_normalize_info.row_counts = {"customer": 1}
            return mock

        with (
            patch.object(DataImportPipelineSync, "_create_pipeline", mock_create_pipeline),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_sync.validate_schema_and_update_table_sync"
            ) as mock_validate_schema_and_update_table,
            patch("posthog.temporal.data_imports.pipelines.pipeline_sync.get_delta_tables"),
            patch("posthog.temporal.data_imports.pipelines.pipeline_sync.update_last_synced_at_sync"),
            override_settings(
                BUCKET_URL=f"s3://{BUCKET_NAME}",
                AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                AIRBYTE_BUCKET_REGION="us-east-1",
                AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
            ),
        ):
            pipeline = self._create_pipeline("Customer", False)
            res = pipeline.run()

            assert res.get("customer") == 1
            assert mock_validate_schema_and_update_table.call_count == 1

    @pytest.mark.django_db(transaction=True)
    def test_pipeline_incremental(self):
        def mock_create_pipeline(local_self: Any):
            mock = MagicMock()
            type(mock.last_trace.last_normalize_info).row_counts = PropertyMock(side_effect=[{"customer": 1}, {}])
            return mock

        with (
            patch.object(DataImportPipelineSync, "_create_pipeline", mock_create_pipeline),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_sync.validate_schema_and_update_table_sync"
            ) as mock_validate_schema_and_update_table,
            patch("posthog.temporal.data_imports.pipelines.pipeline_sync.get_delta_tables"),
            patch("posthog.temporal.data_imports.pipelines.pipeline_sync.update_last_synced_at_sync"),
            patch("posthog.temporal.data_imports.pipelines.pipeline_sync.save_last_incremental_value"),
            override_settings(
                BUCKET_URL=f"s3://{BUCKET_NAME}",
                AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                AIRBYTE_BUCKET_REGION="us-east-1",
                AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
            ),
        ):
            pipeline = self._create_pipeline("Customer", True)
            res = pipeline.run()

            assert res.get("customer") == 1
            assert mock_validate_schema_and_update_table.call_count == 2
