import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import dlt
import dlt.common
import dlt.common.libs
import dlt.common.libs.pyarrow
import dlt.extract
import dlt.extract.incremental
import dlt.extract.incremental.transform
import pendulum
import pyarrow
from clickhouse_driver.errors import ServerException
from django.conf import settings
from django.db.models import Prefetch
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable


def _from_arrow_scalar(arrow_value: pyarrow.Scalar) -> Any:
    """Converts arrow scalar into Python type. Currently adds "UTC" to naive date times and converts all others to UTC"""
    row_value = arrow_value.as_py()

    if isinstance(row_value, date) and not isinstance(row_value, datetime):
        return row_value
    elif isinstance(row_value, datetime):
        row_value = pendulum.instance(row_value).in_tz("UTC")
    return row_value


dlt.common.libs.pyarrow.from_arrow_scalar = _from_arrow_scalar
dlt.extract.incremental.transform.from_arrow_scalar = _from_arrow_scalar


@dataclass
class PipelineInputs:
    source_id: uuid.UUID
    run_id: str
    schema_id: uuid.UUID
    dataset_name: str
    job_type: ExternalDataSource.Type
    team_id: int


def update_last_synced_at_sync(job_id: str, schema_id: str, team_id: int) -> None:
    job = ExternalDataJob.objects.get(pk=job_id)
    schema = ExternalDataSchema.objects.exclude(deleted=True).get(id=schema_id, team_id=team_id)
    schema.last_synced_at = job.created_at
    schema.save()


def validate_schema_and_update_table_sync(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    table_schema_dict: Optional[dict[str, str]] = None,
) -> None:
    """

    Validates the schemas of data that has been synced by external data job.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern.

    Arguments:
        run_id: The id of the external data job
        team_id: The id of the team
        schema_id: The schema for which the data job relates to
        row_count: The count of synced rows
        table_format: The format of the table
        table_schema_dict: The schema of the table
    """

    logger = bind_temporal_worker_logger_sync(team_id=team_id)

    if row_count == 0:
        logger.warn("Skipping `validate_schema_and_update_table` due to `row_count` being 0")
        return

    job = ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=run_id)

    credential = get_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    external_data_schema = (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )

    _schema_id = external_data_schema.id
    _schema_name: str = external_data_schema.name
    incremental_or_append = external_data_schema.should_use_incremental_field

    table_name = f"{job.pipeline.prefix or ''}{job.pipeline.source_type}_{_schema_name}".lower()
    normalized_schema_name = NamingConvention().normalize_identifier(_schema_name)
    new_url_pattern = job.url_pattern_by_schema(normalized_schema_name)

    # Check
    try:
        logger.info(f"Row count for {_schema_name} ({_schema_id}) is {row_count}")

        table_params = {
            "credential": credential,
            "name": table_name,
            "format": table_format,
            "url_pattern": new_url_pattern,
            "team_id": team_id,
            "row_count": row_count,
        }

        # create or update
        table_created: DataWarehouseTable | None = external_data_schema.table
        if table_created:
            table_created.credential = table_params["credential"]
            table_created.format = table_params["format"]
            table_created.url_pattern = new_url_pattern
            if incremental_or_append:
                table_created.row_count = table_created.get_count()
            else:
                table_created.row_count = row_count
            table_created.save()

        if not table_created:
            table_created = DataWarehouseTable.objects.create(external_data_source_id=job.pipeline.id, **table_params)

        assert isinstance(table_created, DataWarehouseTable) and table_created is not None

        raw_db_columns: dict[str, dict[str, str]] = table_created.get_columns()
        db_columns = {key: column.get("clickhouse", "") for key, column in raw_db_columns.items()}

        columns = {}
        for column_name, db_column_type in db_columns.items():
            hogql_type = table_schema_dict.get(column_name)

            if hogql_type is None:
                capture_exception(Exception(f"HogQL type not found for column: {column_name}"))
                continue

            columns[column_name] = {
                "clickhouse": db_column_type,
                "hogql": hogql_type,
            }
        table_created.columns = columns
        table_created.save()

        # schema could have been deleted by this point
        schema_model = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=_schema_id, team_id=team_id)
        )

        schema_model.table = table_created
        schema_model.save()

    except ServerException as err:
        if err.code == 636:
            logger.exception(
                f"Data Warehouse: No data for schema {_schema_name} for external data job {job.pk}",
                exc_info=err,
            )
        else:
            logger.exception(
                f"Data Warehouse: Unknown ServerException {job.pk}",
                exc_info=err,
            )
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for external data job {job.pk}",
            exc_info=e,
        )
        raise
