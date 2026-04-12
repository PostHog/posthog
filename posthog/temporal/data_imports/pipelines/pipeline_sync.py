import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from django.db import transaction
from django.db.models import Prefetch

import dlt
import pyarrow
import pendulum
import dlt.common
import dlt.extract
import dlt.common.libs
import dlt.common.libs.pyarrow
import dlt.extract.incremental
import dlt.extract.incremental.transform
from clickhouse_driver.errors import ServerException
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.helpers import build_table_name

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


def merge_columns(
    db_columns: dict[str, str],
    table_schema_dict: dict[str, str],
    existing_columns: dict[str, Any],
) -> dict[str, Any]:
    """Build column metadata, preserving StringJSONDatabaseField from prior runs.

    Columns present in existing_columns but absent from db_columns are preserved
    to avoid losing schema information when get_columns() returns incomplete
    results during a sync (e.g., transient S3/ClickHouse introspection failures).
    """
    columns: dict[str, Any] = {}
    for column_name, db_column_type in db_columns.items():
        hogql_type = table_schema_dict.get(column_name)

        if hogql_type is None:
            capture_exception(Exception(f"HogQL type not found for column: {column_name}"))
            continue

        existing_column = existing_columns.get(column_name)
        existing_hogql_type = existing_column.get("hogql") if isinstance(existing_column, dict) else None
        if existing_hogql_type == "StringJSONDatabaseField" and hogql_type == "StringDatabaseField":
            hogql_type = "StringJSONDatabaseField"

        columns[column_name] = {
            "clickhouse": db_column_type,
            "hogql": hogql_type,
        }

    # Preserve columns from prior syncs that are missing from the current introspection.
    # This prevents column loss when get_columns() returns partial results mid-sync.
    for column_name, column_meta in existing_columns.items():
        if column_name in columns:
            continue

        if isinstance(column_meta, dict):
            columns[column_name] = column_meta
        elif isinstance(column_meta, str):
            columns[column_name] = {
                "clickhouse": column_meta,
                "hogql": table_schema_dict.get(column_name, "StringDatabaseField"),
            }

    return columns


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
    job_type: ExternalDataSourceType
    team_id: int


async def update_last_synced_at(job_id: str, schema_id: str, team_id: int) -> None:
    @database_sync_to_async_pool
    def _update():
        job = ExternalDataJob.objects.get(pk=job_id)
        schema = ExternalDataSchema.objects.exclude(deleted=True).get(id=schema_id, team_id=team_id)
        schema.last_synced_at = job.created_at
        schema.save()

    await _update()


async def set_initial_sync_complete(schema_id: str, team_id: int) -> None:
    @database_sync_to_async_pool
    def _update():
        schema = ExternalDataSchema.objects.exclude(deleted=True).get(id=schema_id, team_id=team_id)
        if not schema.initial_sync_complete:
            schema.initial_sync_complete = True
            update_fields = ["initial_sync_complete"]

            # CDC snapshot → streaming transition
            if schema.is_cdc and schema.cdc_mode == "snapshot":
                schema.sync_type_config["cdc_mode"] = "streaming"
                update_fields.append("sync_type_config")

            schema.save(update_fields=update_fields)

    await _update()


async def validate_schema_and_update_table(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: Optional[dict[str, str]] = None,
) -> None:
    """
    Async version of validate_schema_and_update_table_sync.

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
    logger = LOGGER.bind(team_id=team_id)

    if row_count == 0:
        logger.warning("Skipping `validate_schema_and_update_table` due to `row_count` being 0")
        return

    @database_sync_to_async_pool
    def _validate_and_update():
        job = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(pk=run_id)

        external_data_schema = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=schema_id, team_id=team_id)
        )

        _schema_id = external_data_schema.id
        _schema_name: str = external_data_schema.name
        incremental_or_append = external_data_schema.should_use_incremental_field

        table_name = build_table_name(job.pipeline, _schema_name)
        normalized_schema_name = NamingConvention().normalize_identifier(_schema_name)
        new_url_pattern = job.url_pattern_by_schema(normalized_schema_name)

        # Check
        try:
            with transaction.atomic():
                logger.info(f"Row count for {_schema_name} ({_schema_id}) is {row_count}")

                table_params = {
                    "name": table_name,
                    "format": table_format,
                    "url_pattern": new_url_pattern,
                    "team_id": team_id,
                    "row_count": row_count,
                    "queryable_folder": queryable_folder,
                }

                # create or update
                table_created: DataWarehouseTable | None = external_data_schema.table
                if table_created:
                    table_created.format = table_params["format"]
                    table_created.url_pattern = new_url_pattern
                    table_created.queryable_folder = queryable_folder
                    if incremental_or_append or external_data_schema.is_cdc:
                        table_created.row_count = table_created.get_count()
                    else:
                        table_created.row_count = row_count
                    table_created.save()

                if not table_created:
                    # Check if we already have an orphaned table that we can repurpose
                    existing_tables = DataWarehouseTable.objects.filter(
                        team_id=team_id, name=table_name, external_data_source_id=job.pipeline.id, deleted=False
                    )
                    existing_tables_count = existing_tables.count()
                    if existing_tables_count > 0:
                        table_created = existing_tables[0]
                        logger.debug(
                            f"Found {existing_tables_count} existing tables - skipping creating and using {table_created.id}"
                        )

                    if not table_created:
                        logger.debug(f"Creating table for schema: {str(schema_id)}")
                        table_created = DataWarehouseTable.objects.create(
                            external_data_source_id=job.pipeline.id, **table_params
                        )

                assert isinstance(table_created, DataWarehouseTable) and table_created is not None

                raw_db_columns = table_created.get_columns()
                db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}

                # select_for_update prevents two concurrent sync operations from
                # causing a lost-update: both would read the current columns,
                # merge independently, and one write would overwrite the other.
                # Use raw_objects to skip the default manager's select_related —
                # its nullable LEFT JOINs are rejected by Postgres under FOR UPDATE.
                table_for_update = DataWarehouseTable.raw_objects.select_for_update().get(id=table_created.id)
                existing_columns = table_for_update.columns or {}
                columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)
                table_for_update.columns = columns
                table_for_update.save(update_fields=["columns"])
                # Keep local reference in sync
                table_created.columns = columns

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

    await _validate_and_update()


async def register_cdc_companion_table(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    resource_name: str,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: Optional[dict[str, str]] = None,
    set_as_schema_table: bool = False,
) -> None:
    """Create or update a standalone DataWarehouseTable for a CDC companion resource (e.g. `{schema_name}_cdc`).

    Unlike `validate_schema_and_update_table`, this does NOT update `schema.table` — the companion table is
    independent of the main schema table so that writing CDC history never overwrites the snapshot queryable folder.

    When ``set_as_schema_table`` is True (used for cdc_only mode), the companion table is also linked as the
    schema's primary table so the UI shows row counts and query links.
    """
    logger = LOGGER.bind(team_id=team_id)

    if row_count == 0:
        await logger.awarning("Skipping `register_cdc_companion_table` due to `row_count` being 0")
        return

    @database_sync_to_async_pool
    def _register():
        job = ExternalDataJob.objects.prefetch_related("pipeline").get(pk=run_id)

        normalized_resource_name = NamingConvention().normalize_identifier(resource_name)
        companion_table_name = build_table_name(job.pipeline, resource_name)
        new_url_pattern = job.url_pattern_by_schema(normalized_resource_name)

        table_params = {
            "name": companion_table_name,
            "format": table_format,
            "url_pattern": new_url_pattern,
            "team_id": team_id,
            "row_count": row_count,
            "queryable_folder": queryable_folder,
        }

        try:
            with transaction.atomic():
                # Find existing companion table (not schema.table) by name
                companion_table: DataWarehouseTable | None = DataWarehouseTable.objects.filter(
                    team_id=team_id,
                    name=companion_table_name,
                    external_data_source_id=job.pipeline.id,
                    deleted=False,
                ).first()

                if companion_table:
                    companion_table.format = table_format
                    companion_table.url_pattern = new_url_pattern
                    companion_table.queryable_folder = queryable_folder
                    companion_table.row_count = companion_table.get_count()
                    companion_table.save()
                else:
                    logger.debug(f"Creating CDC companion table: {companion_table_name}")
                    companion_table = DataWarehouseTable.objects.create(
                        external_data_source_id=job.pipeline.id, **table_params
                    )

                raw_db_columns = companion_table.get_columns()
                db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}
                existing_columns = companion_table.columns or {}
                columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)
                companion_table.columns = columns
                companion_table.save()

                if set_as_schema_table:
                    ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id).update(table=companion_table)

        except Exception as e:
            logger.exception(
                f"Data Warehouse: Could not register CDC companion table {companion_table_name}",
                exc_info=e,
            )
            raise

    await _register()
