import json
from collections.abc import Sequence
from typing import Any
import uuid
import pyarrow as pa
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.sources import DltResource
import deltalake as deltalake
from django.db.models import F
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema


def _get_primary_keys(resource: DltResource) -> list[Any] | None:
    primary_keys = resource._hints.get("primary_key")

    if primary_keys is None:
        return None

    if isinstance(primary_keys, str):
        return [primary_keys]

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


def _update_incremental_state(schema: ExternalDataSchema | None, table: pa.Table, logger: FilteringBoundLogger) -> None:
    if schema is None or schema.sync_type != ExternalDataSchema.SyncType.INCREMENTAL:
        return

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return

    column = table[incremental_field_name]
    numpy_arr = column.combine_chunks().to_pandas().to_numpy()

    # TODO(@Gilbert09): support different operations here (e.g. min)
    last_value = numpy_arr.max()

    logger.debug(f"Updating incremental_field_last_value_v2 with {last_value}")

    schema.update_incremental_field_last_value(last_value)


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
