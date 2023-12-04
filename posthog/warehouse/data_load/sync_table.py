from django.conf import settings
from django.db.models import Q

from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.temporal.common.logger import bind_temporal_worker_logger
import s3fs
from asgiref.sync import async_to_sync


class SchemaValidationError(Exception):
    def __init__(self):
        super().__init__(f"Schema validation failed")


def get_latest_run_if_exists(team_id: int, pipeline_id: str) -> ExternalDataJob | None:
    job = (
        ExternalDataJob.objects.filter(
            team_id=team_id, pipeline_id=pipeline_id, status=ExternalDataJob.Status.COMPLETED
        )
        .order_by("-created_at")
        .first()
    )

    return job


def get_s3_client():
    return s3fs.S3FileSystem(
        key=settings.AIRBYTE_BUCKET_KEY,
        secret=settings.AIRBYTE_BUCKET_SECRET,
    )


# TODO: make async
def validate_schema_and_update_table(run_id: str, team_id: int) -> None:
    logger = async_to_sync(bind_temporal_worker_logger)(team_id=team_id)

    job = ExternalDataJob.objects.get(pk=run_id)
    last_successful_job = get_latest_run_if_exists(job.team_id, job.pipeline_id)
    s3 = get_s3_client()
    bucket_name = settings.BUCKET_URL

    credential, _ = DataWarehouseCredential.objects.get_or_create(
        team_id=job.team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    source_schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[job.pipeline.source_type]

    def get_url_pattern(folder_path: str, schema_name: str) -> str:
        return f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{folder_path}/{schema_name.lower()}/*.parquet"

    for _schema_name in source_schemas:
        table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{_schema_name}".lower()
        new_url_pattern = get_url_pattern(job.folder_path, _schema_name)

        # Check
        data = {
            "credential": credential,
            "name": table_name,
            "format": "Parquet",
            "url_pattern": new_url_pattern,
            "team_id": job.team_id,
        }

        table = DataWarehouseTable(**data)

        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Sync Resource failed with an unexpected exception for connection: {job.pipeline.pk}",
                exc_info=e,
            )
            raise SchemaValidationError()

        # create or update

        table_created = None
        if last_successful_job:
            old_url_pattern = get_url_pattern(last_successful_job.folder_path, _schema_name)
            try:
                table_created = DataWarehouseTable.objects.filter(Q(deleted=False) | Q(deleted__isnull=True)).get(
                    team_id=job.team_id, external_data_source_id=job.pipeline.id, url_pattern=old_url_pattern
                )
                table_created.url_pattern = new_url_pattern
                table_created.save()
            except Exception:
                table_created = None

        if not table_created:
            table_created = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **data)

        table_created.columns = table_created.get_columns()
        table_created.save()

    if last_successful_job:
        try:
            s3.delete(f"{bucket_name}/{last_successful_job.folder_path}", recursive=True)
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Could not delete deprecated data source {last_successful_job.pk}",
                exc_info=e,
            )
            pass
