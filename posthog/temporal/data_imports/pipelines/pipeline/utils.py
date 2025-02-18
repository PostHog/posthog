import asyncio
import dataclasses
import decimal
import json
from collections.abc import Sequence
import math
from typing import Any, Optional
from collections.abc import Hashable
from collections.abc import Iterator
from dateutil import parser
import uuid
import orjson
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.sources import DltResource
import deltalake as deltalake
from django.db.models import F
from posthog.constants import DATA_WAREHOUSE_COMPACTION_TASK_QUEUE
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import FilteringBoundLogger
from dlt.common.data_types.typing import TDataType
from dlt.common.normalizers.naming.snake_case import NamingConvention
from posthog.temporal.data_imports.deltalake_compaction_job import DeltalakeCompactionJobWorkflowInputs
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema

DLT_TO_PA_TYPE_MAP = {
    "text": pa.string(),
    "bigint": pa.int64(),
    "bool": pa.bool_(),
    "timestamp": pa.timestamp("us"),
    "json": pa.string(),
    "double": pa.float64(),
    "date": pa.date64(),
    "time": pa.timestamp("us"),
    "decimal": pa.float64(),
}


def normalize_column_name(column_name: str) -> str:
    return NamingConvention().normalize_identifier(column_name)


def safe_parse_datetime(date_str):
    try:
        if date_str is None:
            return None

        if isinstance(date_str, pa.StringScalar):
            scalar = date_str.as_py()

            if scalar is None:
                return None

            return parser.parse(scalar)

        return parser.parse(date_str)
    except (ValueError, OverflowError, TypeError):
        return None


def _get_primary_keys(resource: DltResource) -> list[str] | None:
    primary_keys = resource._hints.get("primary_key")

    if primary_keys is None:
        return None

    if isinstance(primary_keys, str):
        return [normalize_column_name(primary_keys)]

    if isinstance(primary_keys, list | Sequence):
        return [normalize_column_name(pk) for pk in primary_keys]

    raise Exception(f"primary_keys of type {primary_keys.__class__.__name__} are not supported")


def _get_column_hints(resource: DltResource) -> dict[str, TDataType | None] | None:
    columns = resource._hints.get("columns")

    if columns is None:
        return None

    return {key: value.get("data_type") for key, value in columns.items()}  # type: ignore


def _handle_null_columns_with_definitions(table: pa.Table, source: SourceResponse) -> pa.Table:
    column_hints = source.column_hints

    if column_hints is None:
        return table

    for field_name, data_type in column_hints.items():
        if data_type is None:
            continue

        normalized_field_name = normalize_column_name(field_name)
        # If the table doesn't have all fields, then add a field with all Nulls and the correct field type
        if normalized_field_name not in table.schema.names:
            new_column = pa.array([None] * table.num_rows, type=DLT_TO_PA_TYPE_MAP[data_type])
            table = table.append_column(normalized_field_name, new_column)

    return table


def _evolve_pyarrow_schema(table: pa.Table, delta_schema: deltalake.Schema | None) -> pa.Table:
    py_table_field_names = table.schema.names

    for column_name in table.column_names:
        column = table.column(column_name)

        # Change pa.structs to JSON string
        if pa.types.is_struct(column.type) or pa.types.is_list(column.type):
            json_column = pa.array([json.dumps(row.as_py()) if row.as_py() is not None else None for row in column])
            table = table.set_column(table.schema.get_field_index(column_name), column_name, json_column)
            column = table.column(column_name)
        # Change pa.duration to int with total seconds
        elif pa.types.is_duration(column.type):
            seconds_column = pa.array(
                [row.as_py().total_seconds() if row.as_py() is not None else None for row in column]
            )
            table = table.set_column(table.schema.get_field_index(column_name), column_name, seconds_column)
            column = table.column(column_name)

        # Normalize column names
        normalized_column_name = normalize_column_name(column_name)
        if normalized_column_name != column_name:
            table = table.set_column(table.schema.get_field_index(column_name), normalized_column_name, column)

    # Refresh column names after potential name updates
    py_table_field_names = table.schema.names

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

            # If the delta table schema has a larger scale/precision, then update the
            # pyarrow schema to use the larger values so that we're not trying to downscale
            if isinstance(field.type, pa.Decimal128Type) or isinstance(field.type, pa.Decimal256Type):
                py_arrow_table_column = table.column(field.name)
                assert isinstance(py_arrow_table_column.type, pa.Decimal128Type) or isinstance(
                    py_arrow_table_column.type, pa.Decimal256Type
                )

                if (
                    field.type.precision > py_arrow_table_column.type.precision
                    or field.type.scale > py_arrow_table_column.type.scale
                ):
                    field_index = table.schema.get_field_index(field.name)

                    new_decimal_type = (
                        pa.decimal128(field.type.precision, field.type.scale)
                        if field.type.precision <= 38
                        else pa.decimal256(field.type.precision, field.type.scale)
                    )

                    new_schema = table.schema.set(
                        field_index,
                        table.schema.field(field_index).with_type(new_decimal_type),
                    )
                    table = table.cast(new_schema)

            # If the deltalake schema has a different type to the pyarrows table, then cast to the deltalake field type
            py_arrow_table_column = table.column(field.name)
            if field.type != py_arrow_table_column.type:
                if isinstance(field.type, pa.TimestampType):
                    timestamp_array = pa.array(
                        [safe_parse_datetime(s) for s in table.column(field.name)], type=field.type
                    )
                    table = table.set_column(
                        table.schema.get_field_index(field.name),
                        field.name,
                        timestamp_array,
                    )
                else:
                    table = table.set_column(
                        table.schema.get_field_index(field.name),
                        field.name,
                        table.column(field.name).cast(field.type),
                    )

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


def _update_incremental_state(schema: ExternalDataSchema | None, table: pa.Table, logger: FilteringBoundLogger) -> None:
    if schema is None or schema.sync_type != ExternalDataSchema.SyncType.INCREMENTAL:
        return

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return

    column = table[normalize_column_name(incremental_field_name)]
    numpy_arr = column.combine_chunks().to_pandas().to_numpy()

    # TODO(@Gilbert09): support different operations here (e.g. min)
    last_value = numpy_arr.max()

    logger.debug(f"Updating incremental_field_last_value with {last_value}")

    schema.update_incremental_field_last_value(last_value)


def _update_last_synced_at_sync(schema: ExternalDataSchema, job: ExternalDataJob) -> None:
    schema.last_synced_at = job.created_at
    schema.save()


def _update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    logger.debug(f"Updating rows_synced with +{count}")
    ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)


def _convert_uuid_to_string(row: dict) -> dict:
    return {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}


def _json_dumps(obj: Any) -> str:
    try:
        return orjson.dumps(obj).decode()
    except TypeError as e:
        if str(e) == "Integer exceeds 64-bit range":
            return json.dumps(obj)
        raise TypeError(e)


def table_from_iterator(data_iterator: Iterator[dict], schema: Optional[pa.Schema] = None) -> pa.Table:
    batch = list(data_iterator)
    if not batch:
        return pa.Table.from_pylist([])

    processed_batch = _process_batch(list(batch), schema)

    return processed_batch


def table_from_py_list(table_data: list[Any]) -> pa.Table:
    """
    Convert a list of Python dictionaries to a PyArrow Table.
    This is a wrapper around table_from_iterator for backward compatibility.
    """
    return table_from_iterator(iter(table_data))


def _python_type_to_pyarrow_type(type_: type, value: Any):
    python_to_pa = {
        int: pa.int64(),
        float: pa.float64(),
        str: pa.string(),
        bool: pa.bool_(),
        bytes: pa.binary(),
        type(None): pa.null(),
    }

    if type_ in python_to_pa:
        return python_to_pa[type_]

    if issubclass(type_, dict) and isinstance(value, dict):
        return pa.struct([pa.field(str(k), _python_type_to_pyarrow_type(type(v), v)) for k, v in value.items()])

    if issubclass(type_, list) and isinstance(value, list):
        if len(value) == 0:
            return pa.list_(pa.null())

        return pa.list_(_python_type_to_pyarrow_type(type(value[0]), value[0]))

    raise ValueError(f"Python type {type_} has no pyarrow mapping")


def _process_batch(table_data: list[dict], schema: Optional[pa.Schema] = None) -> pa.Table:
    # Support both given schemas and inferred schemas
    if schema is None:
        try:
            arrow_schema = pa.Table.from_pylist(table_data).schema
        except:
            arrow_schema = None
    else:
        arrow_schema = schema

    drop_column_names: list[Hashable] = []

    columnar_table_data: dict[Hashable, pa.Array | np.ndarray[Any, np.dtype[Any]]] = {
        key: np.array([None if isinstance(x, float) and np.isnan(x) else x for x in values], dtype=object)
        for key, values in pd.DataFrame(table_data, dtype=object).to_dict(orient="list").items()
    }

    for field_name in columnar_table_data.keys():
        py_type: type = type(None)
        unique_types_in_column = {type(item) for item in columnar_table_data[field_name].tolist() if item is not None}

        for row in table_data:
            val = row.get(field_name, None)
            if val is not None:
                py_type = type(val)
                break

        # If a schema is present:
        if arrow_schema:
            if field_name not in arrow_schema.names:
                new_field = pa.field(str(field_name), _python_type_to_pyarrow_type(py_type, val), nullable=True)
                arrow_schema = arrow_schema.append(field=new_field)

            field = arrow_schema.field_by_name(str(field_name))
            field_index = arrow_schema.get_field_index(str(field_name))

            # cast double / float ndarrays to decimals if type mismatch, looks like decimals and floats are often mixed up in dialects
            if pa.types.is_decimal(field.type) and issubclass(py_type, str | float):
                float_array = pa.array(columnar_table_data[field_name], type=pa.float64())
                columnar_table_data[field_name] = float_array.cast(field.type, safe=False)

            # cast string timestamps to datetime objects
            if pa.types.is_timestamp(field.type) and issubclass(py_type, str):
                timestamp_array = pa.array(
                    [safe_parse_datetime(s) for s in columnar_table_data[field_name].tolist()], type=field.type
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()

                adjusted_field = arrow_schema.field(field_index).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

        # Convert UUIDs to strings
        if issubclass(py_type, uuid.UUID):
            uuid_str_array = pa.array([None if s is None else str(s) for s in columnar_table_data[field_name].tolist()])
            columnar_table_data[field_name] = uuid_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # If one type is a list, then make everything into a list
        if len(unique_types_in_column) > 1 and list in unique_types_in_column:
            list_array = pa.array([s if isinstance(s, list) else [s] for s in columnar_table_data[field_name].tolist()])
            columnar_table_data[field_name] = list_array
            py_type = list
            unique_types_in_column = {list}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # If str and dict are shared - then turn everything into a json string
        if len(unique_types_in_column) > 1 and str in unique_types_in_column and dict in unique_types_in_column:
            json_array = pa.array(
                [
                    None if s is None else _json_dumps(s) if isinstance(s, dict | list) else s
                    for s in columnar_table_data[field_name].tolist()
                ]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # If there are multiple types that aren't a list, then JSON stringify everything
        if len(unique_types_in_column) > 1:
            json_array = pa.array(
                [None if s is None else _json_dumps(s) for s in columnar_table_data[field_name].tolist()]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert any dict/lists to json strings to avoid schema mismatches in nested objects
        if issubclass(py_type, dict | list):
            json_str_array = pa.array(
                [None if s is None else _json_dumps(s) for s in columnar_table_data[field_name].tolist()]
            )
            columnar_table_data[field_name] = json_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Remove any NaN or infinite values from decimal columns
        if issubclass(py_type, decimal.Decimal):
            columnar_table_data[field_name] = pa.array(
                [
                    None
                    if x is not None and (math.isnan(x) or (isinstance(x, decimal.Decimal) and x.is_infinite()))
                    else x
                    for x in columnar_table_data[field_name].tolist()
                ],
                type=field.type,
            )

        # Remove any binary columns
        if issubclass(py_type, bytes):
            drop_column_names.append(field_name)

    if len(drop_column_names) != 0:
        for column in drop_column_names:
            del columnar_table_data[column]
            if arrow_schema:
                arrow_schema = arrow_schema.remove(arrow_schema.get_field_index(str(column)))

    return pa.Table.from_pydict(columnar_table_data, schema=arrow_schema)


def trigger_compaction_job(job: ExternalDataJob, schema: ExternalDataSchema) -> str:
    temporal = sync_connect()
    workflow_id = f"{schema.id}-compaction"

    try:
        asyncio.run(
            temporal.start_workflow(
                workflow="deltalake-compaction-job",
                arg=dataclasses.asdict(
                    DeltalakeCompactionJobWorkflowInputs(team_id=job.team_id, external_data_job_id=job.id)
                ),
                id=workflow_id,
                task_queue=str(DATA_WAREHOUSE_COMPACTION_TASK_QUEUE),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["NondeterminismError"],
                ),
            )
        )
    except WorkflowAlreadyStartedError:
        pass

    return workflow_id
