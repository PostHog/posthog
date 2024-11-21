import json
import time
from collections.abc import Sequence
from conditional_cache import lru_cache
from typing import Any
import pyarrow as pa
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention
from dlt.sources import DltSource, DltResource
import deltalake as deltalake
from django.conf import settings
from django.db.models import F
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline_sync import validate_schema_and_update_table_sync
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.warehouse.models import DataWarehouseTable, ExternalDataJob, ExternalDataSchema
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)


class HogQLSchema:
    schema: dict[str, str]

    def __init__(self):
        self.schema = {}

    def add_pyarrow_table(self, table: pa.Table) -> None:
        for field in table.schema:
            self.add_field(field, table.column(field.name))

    def add_field(self, field: pa.Field, column: pa.ChunkedArray) -> None:
        existing_type = self.schema.get(field.name)
        if existing_type is not None and existing_type != StringDatabaseField.__name__:
            return

        hogql_type: type[DatabaseField] = DatabaseField

        if pa.types.is_time(field.type):
            hogql_type = DateTimeDatabaseField
        elif pa.types.is_timestamp(field.type):
            hogql_type = DateTimeDatabaseField
        elif pa.types.is_date(field.type):
            hogql_type = DateDatabaseField
        elif pa.types.is_decimal(field.type):
            hogql_type = FloatDatabaseField
        elif pa.types.is_floating(field.type):
            hogql_type = FloatDatabaseField
        elif pa.types.is_boolean(field.type):
            hogql_type = BooleanDatabaseField
        elif pa.types.is_integer(field.type):
            hogql_type = IntegerDatabaseField
        elif pa.types.is_binary(field.type):
            raise Exception("Type 'binary' is not a supported column type")
        elif pa.types.is_string(field.type):
            hogql_type = StringDatabaseField

            # Checking for JSON string columns with the first non-null value in the column
            for value in column:
                value_str = value.as_py()
                if value_str is not None:
                    assert isinstance(value_str, str)
                    if value_str.startswith("{") or value_str.startswith("["):
                        hogql_type = StringJSONDatabaseField
                    break

        self.schema[field.name] = hogql_type.__name__

    def to_hogql_types(self) -> dict[str, str]:
        return self.schema


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob

    def __init__(self, resource_name: str, job: ExternalDataJob) -> None:
        self._resource_name = resource_name
        self._job = job

    def _get_credentials(self):
        if TEST:
            return {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        return f"{settings.BUCKET_URL}/{self._job.folder_path()}/{normalized_resource_name}"

    def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_pyarrow()

        new_fields = [
            deltalake.Field.from_pyarrow(field)
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            delta_table.alter.add_columns(new_fields)

        return delta_table

    @lru_cache(maxsize=1, condition=lambda result: result is not None)
    def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = self._get_delta_table_uri()
        storage_options = self._get_credentials()

        if deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
            return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)

        return None

    def write_to_deltalake(
        self, data: pa.Table, is_incremental: bool, chunk_index: int, primary_keys: Sequence[Any] | None
    ) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()

        if delta_table:
            delta_table = self._evolve_delta_schema(data.schema)

        if is_incremental and delta_table is not None:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            delta_table.merge(
                source=data,
                source_alias="source",
                target_alias="target",
                predicate=" AND ".join([f"source.{c} = target.{c}" for c in primary_keys]),
            ).when_matched_update_all().when_not_matched_insert_all().execute()
        else:
            mode = "append"
            schema_mode = "merge"
            if chunk_index == 0 or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            if delta_table is None:
                delta_table = deltalake.DeltaTable.create(table_uri=self._get_delta_table_uri(), schema=data.schema)

            deltalake.write_deltalake(
                table_or_uri=delta_table,
                data=data,
                partition_by=None,
                mode=mode,
                schema_mode=schema_mode,
                engine="rust",
            )  # type: ignore

        delta_table = self.get_delta_table()
        assert delta_table is not None

        return delta_table


class PipelineNonDLT:
    _resource: DltResource
    _resource_name: str
    _job: ExternalDataJob
    _schema: ExternalDataSchema
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _delta_table_helper: DeltaTableHelper
    _internal_schema = HogQLSchema()
    _load_id: int

    def __init__(self, source: DltSource, logger: FilteringBoundLogger, job_id: str, is_incremental: bool) -> None:
        resources = list(source.resources.items())
        assert len(resources) == 1
        resource_name, resource = resources[0]

        self._resource = resource
        self._resource_name = resource_name
        self._job = ExternalDataJob.objects.prefetch_related("schema").get(id=job_id)
        self._is_incremental = is_incremental
        self._logger = logger
        self._load_id = time.time_ns()

        schema: ExternalDataSchema | None = self._job.schema
        assert schema is not None
        self._schema = schema

        self._delta_table_helper = DeltaTableHelper(resource_name, self._job)
        self._internal_schema = HogQLSchema()

    def run(self):
        buffer: list[Any] = []
        chunk_size = 5000
        row_count = 0
        chunk_index = 0

        for item in self._resource:
            py_table = None

            if isinstance(item, list):
                if len(buffer) > 0:
                    buffer.extend(item)
                    if len(buffer) >= chunk_size:
                        py_table = pa.Table.from_pylist(buffer)
                        buffer = []
                else:
                    if len(item) >= chunk_size:
                        py_table = pa.Table.from_pylist(item)
                    else:
                        buffer.extend(item)
                        continue
            elif isinstance(item, dict):
                buffer.append(item)
                if len(buffer) < chunk_size:
                    continue

                py_table = pa.Table.from_pylist(buffer)
                buffer = []
            elif isinstance(item, pa.Table):
                py_table = item
            else:
                raise Exception(f"Unhandled item type: {item.__class__.__name__}")

            assert py_table is not None

            self._process_pa_table(pa_table=py_table, index=chunk_index)

            row_count += py_table.num_rows
            chunk_index += 1

        if len(buffer) > 0:
            py_table = pa.Table.from_pylist(buffer)
            self._process_pa_table(pa_table=py_table, index=chunk_index)
            row_count += py_table.num_rows

        self._post_run_operations(row_count=row_count)

    def _process_pa_table(self, pa_table: pa.Table, index: int):
        delta_table = self._delta_table_helper.get_delta_table()

        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)

        table_primary_keys = self._get_primary_keys()
        delta_table = self._delta_table_helper.write_to_deltalake(
            pa_table, self._is_incremental, index, table_primary_keys
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        _update_incrementality(self._schema, pa_table, self._logger)
        _update_job_row_count(self._job.id, pa_table.num_rows, self._logger)

    def _post_run_operations(self, row_count: int):
        delta_table = self._delta_table_helper.get_delta_table()

        assert delta_table is not None

        self._logger.info("Compacting delta table")
        delta_table.optimize.compact()
        delta_table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

        file_uris = delta_table.file_uris()
        self._logger.info(f"Preparing S3 files - total parquet files: {len(file_uris)}")
        prepare_s3_files_for_querying(self._job.folder_path(), self._resource_name, file_uris)

        self._logger.debug("Validating schema and updating table")

        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema={},
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

    def _get_primary_keys(self) -> list[Any] | None:
        primary_keys = self._resource._hints.get("primary_key")

        if primary_keys is None:
            return None

        if isinstance(primary_keys, list):
            return primary_keys

        if isinstance(primary_keys, Sequence):
            return list(primary_keys)

        raise Exception(f"primary_keys of type {primary_keys.__class__.__name__} are not supported")


def _evolve_pyarrow_schema(table: pa.Table, delta_schema: deltalake.Schema | None) -> pa.Table:
    py_table_field_names = table.schema.names

    # Change pa.structs to JSON string
    for column_name in table.column_names:
        column = table.column(column_name)
        if pa.types.is_struct(column.type) or pa.types.is_list(column.type):
            json_column = pa.array([json.dumps(row.as_py()) if row.as_py() is not None else None for row in column])
            table = table.set_column(table.schema.get_field_index(column_name), column_name, json_column)

    if delta_schema:
        for field in delta_schema.to_pyarrow():
            if field.name not in py_table_field_names:
                if field.nullable:
                    new_column_data = pa.array([None] * table.num_rows, type=field.type)
                else:
                    new_column_data = pa.array(
                        [_get_default_value_from_pyarrow_type(field.type)] * table.num_rows, type=field.type
                    )
                table = table.append_column(field, new_column_data)

    # Change types based on what deltalake tables support
    return table.cast(ensure_delta_compatible_arrow_schema(table.schema))


def _append_debug_column_to_pyarrows_table(table: pa.Table, load_id: int) -> pa.Table:
    debug_info = f'{{"load_id": {load_id}}}'

    column = pa.array([debug_info] * table.num_rows, type=pa.string())
    return table.append_column("_ph_debug", column)


def _get_default_value_from_pyarrow_type(pyarrow_type: pa.DataType):
    """
    Returns a default value for the given PyArrow type.
    """
    if pa.types.is_integer(pyarrow_type):
        return 0
    elif pa.types.is_floating(pyarrow_type):
        return 0.0
    elif pa.types.is_string(pyarrow_type):
        return ""
    elif pa.types.is_boolean(pyarrow_type):
        return False
    elif pa.types.is_binary(pyarrow_type):
        return b""
    elif pa.types.is_timestamp(pyarrow_type):
        return pa.scalar(0, type=pyarrow_type).as_py()
    elif pa.types.is_date(pyarrow_type):
        return pa.scalar(0, type=pyarrow_type).as_py()
    elif pa.types.is_time(pyarrow_type):
        return pa.scalar(0, type=pyarrow_type).as_py()
    else:
        raise ValueError(f"No default value defined for type: {pyarrow_type}")


def _update_incrementality(schema: ExternalDataSchema | None, table: pa.Table, logger: FilteringBoundLogger) -> None:
    if schema is None or schema.sync_type != ExternalDataSchema.SyncType.INCREMENTAL:
        return

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return

    column = table[incremental_field_name]
    numpy_arr = column.combine_chunks().to_pandas().to_numpy()

    # TODO(@Gilbert09): support different operations here (e.g. min)
    last_value = numpy_arr.max()

    logger.debug(f"Updating incremental_field_last_value with {last_value}")

    schema.update_incremental_field_last_value(last_value)


def _update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    logger.debug(f"Updating rows_synced with +{count}")
    ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)
