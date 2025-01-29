import json
from collections.abc import Sequence
from typing import Any
from dateutil import parser
import uuid
import pyarrow as pa
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.sources import DltResource
import deltalake as deltalake
from django.db.models import F
from posthog.temporal.common.logger import FilteringBoundLogger
from dlt.common.data_types.typing import TDataType
from dlt.common.normalizers.naming.snake_case import NamingConvention
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


def _get_primary_keys(resource: DltResource) -> list[Any] | None:
    primary_keys = resource._hints.get("primary_key")

    if primary_keys is None:
        return None

    if isinstance(primary_keys, str):
        return [normalize_column_name(primary_keys)]

    if isinstance(primary_keys, list | Sequence):
        return [normalize_column_name(pk) for pk in primary_keys]

    raise Exception(f"primary_keys of type {primary_keys.__class__.__name__} are not supported")


def _get_column_hints(resource: DltResource) -> dict[str, TDataType] | None:
    columns = resource._hints.get("columns")

    if columns is None:
        return None

    return {key: value.get("data_type") for key, value in columns.items()}  # type: ignore


def _handle_null_columns_with_definitions(table: pa.Table, resource: DltResource) -> pa.Table:
    column_hints = _get_column_hints(resource)

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
            if isinstance(field.type, pa.Decimal128Type):
                py_arrow_table_column = table.column(field.name)
                if (
                    field.type.precision > py_arrow_table_column.type.precision
                    or field.type.scale > py_arrow_table_column.type.scale
                ):
                    field_index = table.schema.get_field_index(field.name)
                    new_schema = table.schema.set(
                        field_index,
                        table.schema.field(field_index).with_type(
                            pa.decimal128(field.type.precision, field.type.scale)
                        ),
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


def _convert_uuid_to_string(table_data: list[Any]) -> list[dict]:
    return [
        {key: (str(value) if isinstance(value, uuid.UUID) else value) for key, value in record.items()}
        for record in table_data
    ]


def table_from_py_list(table_data: list[Any]) -> pa.Table:
    try:
        if len(table_data) == 0:
            return pa.Table.from_pylist(table_data)

        uuid_exists = any(isinstance(value, uuid.UUID) for value in table_data[0].values())
        if uuid_exists:
            return pa.Table.from_pylist(_convert_uuid_to_string(table_data))

        return pa.Table.from_pylist(table_data)
    except:
        # There exists mismatched types in the data
        column_types: dict[str, set[type]] = {key: set() for key in table_data[0].keys()}

        for row in table_data:
            for column, value in row.items():
                column_types[column].add(type(value))

        inconsistent_columns = {column: types for column, types in column_types.items() if len(types) > 1}

        for column_name, types in inconsistent_columns.items():
            if list not in types:
                raise

            # If one type is a list, then make everything into a list
            for row in table_data:
                value = row[column_name]
                if not isinstance(value, list):
                    row[column_name] = [value]

        return pa.Table.from_pylist(table_data)
