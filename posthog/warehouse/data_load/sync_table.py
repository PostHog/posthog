import structlog
from django.conf import settings
from django.db.models import Q
import s3fs

from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.models.external_data_job import ExternalDataJob

logger = structlog.get_logger(__name__)


class SchemaValidationError(Exception):
    def __init__(self):
        super().__init__(f"Schema validation failed")


# TODO: make async
def is_schema_valid(run_id: str, create: bool = False) -> bool:
    job = ExternalDataJob.objects.get(pk=run_id)
    credential, _ = DataWarehouseCredential.objects.get_or_create(
        team_id=job.team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    source_schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[job.pipeline.source_type]

    for schema_name in source_schemas:
        table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{schema_name}".lower()

        folder_path = job.folder_path if create else job.draft_folder_path
        url_pattern = f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{folder_path}/{schema_name.lower()}/*.parquet"

        data = {
            "credential": credential,
            "name": table_name,
            "format": "Parquet",
            "url_pattern": url_pattern,
            "team_id": job.team_id,
        }

        if create:
            exists = (
                DataWarehouseTable.objects.filter(
                    team_id=job.team_id, external_data_source_id=job.pipeline.id, url_pattern=url_pattern
                )
                .filter(Q(deleted=False) | Q(deleted__isnull=True))
                .exists()
            )

            if exists:
                table = DataWarehouseTable.objects.filter(Q(deleted=False) | Q(deleted__isnull=True)).get(
                    team_id=job.team_id, external_data_source_id=job.pipeline.id, url_pattern=url_pattern
                )
            else:
                table = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **data)
        else:
            table = DataWarehouseTable(**data)

        try:
            table.columns = table.get_columns()
        except Exception as e:
            logger.exception(
                f"Data Warehouse: Sync Resource failed with an unexpected exception for connection: {job.pipeline.pk}",
                exc_info=e,
            )
            raise SchemaValidationError()
        else:
            if create:
                table.save()

    return True


def get_s3fs():
    return s3fs.S3FileSystem(key=settings.AIRBYTE_BUCKET_KEY, secret=settings.AIRBYTE_BUCKET_SECRET)


# TODO: Make this a proper async function with boto3...
def move_draft_to_production(team_id: int, run_id: str):
    model = ExternalDataJob.objects.get(team_id=team_id, id=run_id)
    bucket_name = settings.BUCKET_URL
    s3 = get_s3fs()
    try:
        s3.copy(
            f"{bucket_name}/{model.draft_folder_path}",
            f"{bucket_name}/{model.draft_folder_path}_success",
            recursive=True,
        )
    except FileNotFoundError:
        # TODO: log
        pass

    try:
        s3.delete(f"{bucket_name}/{model.folder_path}", recursive=True)
    except FileNotFoundError:
        # This folder won't exist on initial run
        pass

    try:
        s3.copy(
            f"{bucket_name}/{model.draft_folder_path}_success", f"{bucket_name}/{model.folder_path}", recursive=True
        )
    except FileNotFoundError:
        pass

    s3.delete(f"{bucket_name}/{model.draft_folder_path}_success", recursive=True)
    s3.delete(f"{bucket_name}/{model.draft_folder_path}", recursive=True)
