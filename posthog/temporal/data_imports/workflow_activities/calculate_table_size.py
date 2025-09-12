import dataclasses

from django.conf import settings
from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models import DataWarehouseTable
from posthog.temporal.common.logger import get_logger
from posthog.warehouse.models import ExternalDataSchema
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.s3 import get_size_of_folder

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CalculateTableSizeActivityInputs:
    team_id: int
    schema_id: str
    job_id: str


@activity.defn
def calculate_table_size_activity(inputs: CalculateTableSizeActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    logger.debug("Calculating table size in S3")

    try:
        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        logger.debug(f"Schema doesnt exist, exiting early. Schema id = {inputs.schema_id}")
        return

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
    except ExternalDataJob.DoesNotExist:
        logger.debug(f"Job doesnt exist, exiting early. Job id = {inputs.job_id}")
        return

    table: DataWarehouseTable | None = schema.table

    if not table:
        logger.debug("Table doesnt exist on schema, exiting early")
        return

    existing_size = table.size_in_s3_mib or 0

    logger.debug(f"Existing size in MiB = {existing_size:.2f}")

    folder_name = schema.folder_path()
    if table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper:
        s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}__query"
    else:
        s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}"

    total_mib = get_size_of_folder(s3_folder)

    logger.debug(f"Total size in MiB = {total_mib:.2f}")

    table_size_delta = total_mib - existing_size
    logger.debug(f"Table size delta in MiB = {table_size_delta:.2f}")

    job.storage_delta_mib = table_size_delta
    job.save()

    table.size_in_s3_mib = total_mib
    table.save()

    logger.debug("Table model updated")
