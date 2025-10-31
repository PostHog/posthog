import json
import math
import uuid
import decimal
import hashlib
import datetime
from collections.abc import Iterator, Sequence
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any, Optional, cast

import numpy as np
import orjson
import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from dateutil import parser
from dlt.common.data_types.typing import TDataType
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention
from dlt.sources import DltResource
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSchema

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

DEFAULT_NUMERIC_PRECISION = 38  # Delta Lake maximum precision
DEFAULT_NUMERIC_SCALE = 32  # Delta Lake maximum scale
DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES = 200 * 1024 * 1024  # 200 MB


class BillingLimitsWillBeReachedException(Exception):
    pass


class DuplicatePrimaryKeysException(Exception):
    pass


class QueryTimeoutException(Exception):
    pass


class TemporaryFileSizeExceedsLimitException(Exception):
    pass


def normalize_column_name(column_name: str) -> str:
    return NamingConvention().normalize_identifier(column_name)


def safe_parse_datetime(date_str) -> None | pa.TimestampScalar | datetime.datetime:
    try:
        if date_str is None:
            return None

        if isinstance(date_str, pa.StringScalar):
            scalar = date_str.as_py()

            if scalar is None:
                return None

            return parser.parse(scalar)

        if isinstance(date_str, pa.TimestampScalar):
            return date_str

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


def get_default_value_for_pyarrow_type(arrow_type: pa.DataType) -> Any:
    if pa.types.is_integer(arrow_type):
        return 0
    elif pa.types.is_floating(arrow_type):
        return 0.0
    elif pa.types.is_boolean(arrow_type):
        return False
    elif pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return ""
    elif pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return b""
    elif pa.types.is_timestamp(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_date(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_time(arrow_type):
        return pa.scalar(0, type=arrow_type).as_py()
    elif pa.types.is_list(arrow_type):
        return []
    elif pa.types.is_struct(arrow_type):
        return {}
    elif pa.types.is_dictionary(arrow_type):
        return {}
    elif pa.types.is_decimal(arrow_type):
        return decimal.Decimal(0)
    elif pa.types.is_duration(arrow_type):
        return 0
    elif pa.types.is_null(arrow_type):
        return None
    else:
        raise ValueError(f"Unsupported PyArrow type: {arrow_type}")


def _evolve_pyarrow_schema(table: pa.Table, delta_schema: deltalake.Schema | None) -> pa.Table:
    py_table_field_names = table.schema.names

    for column_name in table.column_names:
        column = table.column(column_name)
        field = table.field(column_name)

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

        # Convert nanosecond timestamps to microseconds and convert to UTC
        if pa.types.is_timestamp(field.type) and (field.type.unit == "ns" or field.type.tz is not None):
            microsecond_timestamps = pc.cast(column, pa.timestamp("us"), safe=False)
            table = table.set_column(table.schema.get_field_index(column_name), column_name, microsecond_timestamps)

    if delta_schema:
        for field in delta_schema.to_pyarrow():
            if field.name not in py_table_field_names:
                if field.nullable:
                    new_column_data = pa.array([None] * table.num_rows, type=field.type)
                else:
                    new_column_data = pa.array(
                        [get_default_value_for_pyarrow_type(field.type)] * table.num_rows, type=field.type
                    )
                table = table.append_column(field, new_column_data)

            # If the delta table schema has a larger scale/precision, then update the
            # pyarrow schema to use the larger values so that we're not trying to downscale
            if isinstance(field.type, pa.Decimal128Type) or isinstance(field.type, pa.Decimal256Type):
                py_arrow_table_column = table.column(field.name)

                if (
                    isinstance(py_arrow_table_column.type, pa.Decimal128Type)
                    or isinstance(py_arrow_table_column.type, pa.Decimal256Type)
                ) and (
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
                    # If different timezones, cast to the correct tz
                    if (
                        isinstance(py_arrow_table_column.type, pa.TimestampType)
                        and field.type.tz != py_arrow_table_column.type.tz
                    ):
                        casted_column = table.column(field.name).cast(field.type)
                        table = table.set_column(
                            table.schema.get_field_index(field.name),
                            field.name,
                            casted_column.combine_chunks(),
                        )
                    else:
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

                py_arrow_table_column = table.column(field.name)

            py_arrow_table_field = table.field(field.name)
            # If the deltalake schema expects no nulls, but the pyarrow schema is nullable, then fill the nulls
            if not field.nullable and py_arrow_table_field.nullable:
                filled_nulls_arr = py_arrow_table_column.fill_null(
                    fill_value=get_default_value_for_pyarrow_type(py_arrow_table_field.type)
                )
                table = table.set_column(
                    table.schema.get_field_index(field.name), field, filled_nulls_arr.combine_chunks()
                )

    # Change types based on what deltalake tables support
    return table.cast(ensure_delta_compatible_arrow_schema(table.schema))


def _append_debug_column_to_pyarrows_table(table: pa.Table, load_id: int) -> pa.Table:
    debug_info = f'{{"load_id": {load_id}}}'

    column = pa.array([debug_info] * table.num_rows, type=pa.string())
    return table.append_column("_ph_debug", column)


def normalize_table_column_names(table: pa.Table) -> pa.Table:
    used_names = set()

    for column_name in table.column_names:
        normalized_column_name = normalize_column_name(column_name)
        temp_name = normalized_column_name

        if temp_name != column_name:
            while temp_name in used_names or temp_name in table.column_names:
                temp_name = "_" + temp_name

            table = table.set_column(
                table.schema.get_field_index(column_name),
                temp_name,
                table.column(column_name),  # type: ignore
            )
            used_names.add(temp_name)

    return table


PARTITION_DATETIME_COLUMN_NAMES = ["created_at", "inserted_at", "createdAt"]


def setup_partitioning(
    pa_table: pa.Table,
    existing_delta_table: deltalake.DeltaTable | None,
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    logger: FilteringBoundLogger,
) -> pa.Table:
    partition_count = schema.partition_count or resource.partition_count
    partition_size = schema.partition_size or resource.partition_size
    partition_keys = schema.partitioning_keys or resource.partition_keys or resource.primary_keys
    partition_format = schema.partition_format or resource.partition_format
    partition_mode = schema.partition_mode or resource.partition_mode

    if not partition_keys:
        logger.debug("No partition keys, skipping partitioning")
        return pa_table

    if existing_delta_table:
        delta_schema = existing_delta_table.schema().to_pyarrow()
        if PARTITION_KEY not in delta_schema.names:
            logger.debug("Delta table already exists without partitioning, skipping partitioning")
            return pa_table

    partition_result = append_partition_key_to_table(
        table=pa_table,
        partition_count=partition_count,
        partition_size=partition_size,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_format=partition_format,
        logger=logger,
    )

    if partition_result is not None:
        pa_table, partition_mode, partition_format, updated_partition_keys = partition_result

        if (
            not schema.partitioning_enabled
            or schema.partition_mode != partition_mode
            or schema.partition_format != partition_format
            or schema.partitioning_keys != updated_partition_keys
        ):
            logger.debug(
                f"Setting partitioning_enabled on schema with: partition_keys={partition_keys}. partition_count={partition_count}. partition_mode={partition_mode}. partition_format={partition_format}"
            )
            schema.set_partitioning_enabled(
                updated_partition_keys, partition_count, partition_size, partition_mode, partition_format
            )

    return pa_table


def append_partition_key_to_table(
    table: pa.Table,
    partition_count: Optional[int],
    partition_size: Optional[int],
    partition_keys: list[str],
    partition_mode: PartitionMode | None,
    partition_format: PartitionFormat | None,
    logger: FilteringBoundLogger,
) -> None | tuple[pa.Table, PartitionMode, PartitionFormat | None, list[str]]:
    """
    Partitions the pyarrow table via one of three methods:
    - md5: Hashes the primary keys into a fixed number of buckets, the least efficient method of partitioning
    - datetime: Uses a stable timestamp, such as a created_at field, to partition the rows
    - numerical: Uses a numerical primary key to bucket the rows by count
    """

    normalized_partition_keys = [normalize_column_name(key) for key in partition_keys]
    mode: PartitionMode | None = partition_mode

    if mode is None:
        # If the source returns a partition count, then we can bucket by md5
        if partition_count is not None:
            mode = "md5"

        # If there is only one primary key and it's a numerical ID, then bucket by the ID itself instead of hashing it
        is_partition_key_int = pa.types.is_integer(table.field(normalized_partition_keys[0]).type)
        are_incrementing_ints = False
        if is_partition_key_int:
            min_max: dict[str, int] = cast(
                dict[str, int], pc.min_max(table.column(normalized_partition_keys[0])).as_py()
            )
            min_int_val, max_int_val = min_max["min"], min_max["max"]
            range_size = max_int_val - min_int_val + 1
            are_incrementing_ints = table.num_rows / range_size >= 0.2

        if (
            partition_size is not None
            and len(normalized_partition_keys) == 1
            and is_partition_key_int
            and are_incrementing_ints
        ):
            mode = "numerical"
        # If the table has a created_at-ish timestamp, then we can partition by this
        elif any(column_name in table.column_names for column_name in PARTITION_DATETIME_COLUMN_NAMES):
            for column_name in PARTITION_DATETIME_COLUMN_NAMES:
                if (
                    column_name in table.column_names
                    and pa.types.is_timestamp(table.field(column_name).type)
                    and table.column(column_name).null_count != table.num_rows
                ):
                    mode = "datetime"
                    normalized_partition_keys = [column_name]

        if mode is None:
            logger.debug("append_partition_key_to_table: partitioning skipped, no supported partition mode available")
            return None
        else:
            logger.debug(f"append_partition_key_to_table: partitioning mode {mode} selected")

    partition_array: list[str] = []

    for batch in table.to_batches():
        for row in batch.to_pylist():
            if mode == "md5":
                assert partition_count is not None, "append_partition_key_to_table: partition_count is None"

                primary_key_values = [str(row[key]) for key in normalized_partition_keys]
                delimited_primary_key_value = "|".join(primary_key_values)

                hash_value = int(hashlib.md5(delimited_primary_key_value.encode()).hexdigest(), 16)
                partition = hash_value % partition_count

                partition_array.append(str(partition))
            elif mode == "numerical":
                assert partition_size is not None, "append_partition_key_to_table: partition_size is None"

                key = normalized_partition_keys[0]
                partition = row[key] // partition_size

                partition_array.append(str(partition))
            elif mode == "datetime":
                key = normalized_partition_keys[0]
                date = row[key]

                if partition_format is None:
                    partition_format = "month"

                if partition_format == "day":
                    date_format = "%Y-%m-%d"
                elif partition_format == "week":
                    date_format = "%G-w%V"
                elif partition_format == "month":
                    date_format = "%Y-%m"

                if isinstance(date, int):
                    date = datetime.datetime.fromtimestamp(date)
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, datetime.datetime):
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, datetime.date):
                    partition_array.append(date.strftime(date_format))
                elif isinstance(date, str):
                    date = parser.parse(date)
                    partition_array.append(date.strftime(date_format))
                else:
                    partition_array.append("1970-01")
            else:
                raise ValueError(f"Partition mode '{mode}' not supported")

    new_column = pa.array(partition_array, type=pa.string())
    logger.debug(f"append_partition_key_to_table: Partition key added with mode={mode}")

    return table.append_column(PARTITION_KEY, new_column), mode, partition_format, normalized_partition_keys


def _convert_uuid_to_string(row: dict) -> dict:
    return {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}


def _json_dumps(obj: Any) -> str:
    try:
        return orjson.dumps(obj).decode()
    except TypeError:
        try:
            return json.dumps(obj)
        except:
            return str(obj)


def table_from_iterator(data_iterator: Iterator[dict], schema: Optional[pa.Schema] = None) -> pa.Table:
    batch = list(data_iterator)
    if not batch:
        return pa.Table.from_pylist([])

    processed_batch = _process_batch(list(batch), schema)

    return processed_batch


def table_from_py_list(table_data: list[Any], schema: Optional[pa.Schema] = None) -> pa.Table:
    """
    Convert a list of Python dictionaries to a PyArrow Table.
    This is a wrapper around table_from_iterator for backward compatibility.
    """
    return table_from_iterator(iter(table_data), schema=schema)


def build_pyarrow_decimal_type(precision: int, scale: int) -> pa.Decimal128Type | pa.Decimal256Type:
    if precision <= 38:
        return pa.decimal128(precision, scale)
    elif precision <= 76:
        return pa.decimal256(precision, scale)
    else:
        return pa.decimal256(76, max(0, 76 - (precision - scale)))


def _get_max_decimal_type(values: list[decimal.Decimal]) -> pa.Decimal128Type | pa.Decimal256Type:
    """Determine maximum precision and scale from all `decimal.Decimal` values.

    Returns:
        A `pa.Decimal128Type` or `pa.Decimal256Type` with enough precision and
        scale to hold all `values`.
    """
    max_precision = 1
    max_scale = 0

    for value in values:
        _, digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            continue

        # This implementation accounts for leading zeroes being excluded from digits
        # It is based on Arrow, see:
        # https://github.com/apache/arrow/blob/main/python/pyarrow/src/arrow/python/decimal.cc#L75
        if exponent < 0:
            precision = max(len(digits), -exponent)
            scale = -exponent
        else:
            precision = len(digits) + exponent
            scale = 0

        max_precision = max(precision, max_precision)
        max_scale = max(scale, max_scale)

    # Deltalake doesn't like writing decimals with scale of 0 - it auto appends `.0`
    if max_scale == 0:
        max_scale = 1
        max_precision += 1

    return build_pyarrow_decimal_type(max_precision, max_scale)


def _build_decimal_type_from_defaults(values: list[decimal.Decimal | None]) -> pa.Array:
    for decimal_type in [
        pa.decimal128(38, DEFAULT_NUMERIC_SCALE),
        pa.decimal256(76, DEFAULT_NUMERIC_SCALE),
    ]:
        try:
            return pa.array(values, type=decimal_type)
        except:
            pass

    raise ValueError("Cant build a decimal type from defaults")


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

    if issubclass(type_, decimal.Decimal) and isinstance(value, decimal.Decimal):
        sign, digits, exponent = value.as_tuple()
        if isinstance(exponent, int):
            precision = len(digits)
            scale = -exponent if exponent < 0 else 0

            return build_pyarrow_decimal_type(precision, scale)

        return pa.decimal256(DEFAULT_NUMERIC_PRECISION, DEFAULT_NUMERIC_SCALE)

    raise ValueError(f"Python type {type_} has no pyarrow mapping")


def _to_list_array(column_data: pa.Array | pa.ChunkedArray | np.ndarray[Any, np.dtype[Any]]):
    if isinstance(column_data, pa.ChunkedArray):
        return column_data.combine_chunks().tolist()

    return column_data.tolist()


def _process_batch(table_data: list[dict], schema: Optional[pa.Schema] = None) -> pa.Table:
    # Support both given schemas and inferred schemas
    if schema is None or len(schema.names) == 0:
        try:
            # Gather all unique keys from all items, not just the first
            all_keys = set().union(*(d.keys() for d in table_data))
            first_item = table_data[0]
            first_item = {key: first_item.get(key, None) for key in all_keys}
            table_data[0] = first_item
            arrow_schema = pa.Table.from_pylist(table_data).schema
        except:
            arrow_schema = None
    else:
        arrow_schema = schema

    drop_column_names: set[str] = set()

    column_names = set(table_data[0].keys())
    columnar_table_data: dict[str, pa.Array | np.ndarray[Any, np.dtype[Any]]] = {}

    for col in column_names:
        values = [
            None if isinstance(row.get(col, None), float) and np.isnan(row.get(col, None)) else row.get(col, None)
            for row in table_data
        ]

        try:
            # We want to use pyarrow arrays where possible to optimise on memory usage
            columnar_table_data[col] = pa.array(values)
        except:
            # Some values can't be interpreted by pyarrows directly
            columnar_table_data[col] = np.array(values, dtype=object)

    for field_name in columnar_table_data.keys():
        py_type: type = type(None)
        unique_types_in_column = {
            type(item) for item in _to_list_array(columnar_table_data[field_name]) if item is not None
        }

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
            if pa.types.is_decimal(field.type) and (float in unique_types_in_column or str in unique_types_in_column):
                float_array = pa.array(columnar_table_data[field_name], type=pa.float64())
                columnar_table_data[field_name] = float_array.cast(field.type, safe=False)
                unique_types_in_column = {decimal.Decimal}
                py_type = decimal.Decimal
                val = decimal.Decimal(val)

            # cast string timestamps to datetime objects
            if pa.types.is_timestamp(field.type) and issubclass(py_type, str):
                timestamp_array = pa.array(
                    [safe_parse_datetime(s) for s in _to_list_array(columnar_table_data[field_name])], type=field.type
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()

                adjusted_field = arrow_schema.field(field_index).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Upscale second timestamps to microsecond
            if pa.types.is_timestamp(field.type) and issubclass(py_type, int) and field.type.unit == "s":
                timestamp_array = pa.array(
                    [
                        (s * 1_000_000) if s is not None else None
                        for s in _to_list_array(columnar_table_data[field_name])
                    ],
                    type=pa.timestamp("us"),
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()
                adjusted_field = arrow_schema.field(field_index).with_type(pa.timestamp("us")).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Upscale millisecond timestamps to microsecond
            if pa.types.is_timestamp(field.type) and issubclass(py_type, int) and field.type.unit == "ms":
                timestamp_array = pa.array(
                    [(s * 1000) if s is not None else None for s in _to_list_array(columnar_table_data[field_name])],
                    type=pa.timestamp("us"),
                )
                columnar_table_data[field_name] = timestamp_array
                has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()
                adjusted_field = arrow_schema.field(field_index).with_type(pa.timestamp("us")).with_nullable(has_nulls)
                arrow_schema = arrow_schema.set(field_index, adjusted_field)

            # Remove any binary columns
            if pa.types.is_binary(field.type):
                drop_column_names.add(field_name)

            # Ensure duration columns have the correct arrow type
            col = columnar_table_data[field_name]
            if (
                isinstance(col, pa.Array)
                and pa.types.is_duration(col.type)
                and not pa.types.is_duration(arrow_schema.field(field_index).type)
            ):
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(col.type))

        # Convert UUIDs to strings
        if issubclass(py_type, uuid.UUID):
            uuid_str_array = pa.array(
                [None if s is None else str(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = uuid_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Remove any NaN or infinite values from decimal columns
        if issubclass(py_type, decimal.Decimal) or issubclass(py_type, float):

            def _convert_to_decimal_or_none(x: decimal.Decimal | float | None) -> decimal.Decimal | None:
                if x is None:
                    return None

                if (
                    math.isnan(x)
                    or (isinstance(x, decimal.Decimal) and x.is_infinite())
                    or (isinstance(x, float) and np.isinf(x))
                ):
                    return None

                if isinstance(x, decimal.Decimal):
                    return x

                return decimal.Decimal(str(x))

            def _convert_to_float_or_none(x: float | None) -> float | None:
                if x is None:
                    return None

                if math.isnan(x) or np.isinf(x):
                    return None

                return x

            all_values = _to_list_array(columnar_table_data[field_name])

            if len(unique_types_in_column) > 1 or issubclass(py_type, decimal.Decimal):
                # Mixed types: convert all to decimals
                all_values = [_convert_to_decimal_or_none(x) for x in all_values]

                if arrow_schema and pa.types.is_decimal(arrow_schema.field(field_index).type):
                    new_field_type = arrow_schema.field(field_index).type
                else:
                    new_field_type = _get_max_decimal_type([x for x in all_values if x is not None])

                py_type = decimal.Decimal
                unique_types_in_column = {decimal.Decimal}
            elif issubclass(py_type, float):
                all_values = [_convert_to_float_or_none(x) for x in all_values]

                if arrow_schema:
                    new_field_type = arrow_schema.field(field_index).type
                else:
                    new_field_type = pa.float64()

            try:
                number_arr = pa.array(
                    all_values,
                    type=new_field_type,
                )
            except pa.ArrowInvalid as e:
                if len(e.args) > 0 and (
                    "does not fit into precision" in e.args[0] or "would cause data loss" in e.args[0]
                ):
                    number_arr = _build_decimal_type_from_defaults([_convert_to_decimal_or_none(x) for x in all_values])
                    new_field_type = number_arr.type

                    py_type = decimal.Decimal
                    unique_types_in_column = {decimal.Decimal}
                else:
                    raise

            columnar_table_data[field_name] = number_arr
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(new_field_type))

        # If one type is a list, then make everything into a list
        if len(unique_types_in_column) > 1 and list in unique_types_in_column:
            list_array = pa.array(
                [s if isinstance(s, list) else [s] for s in _to_list_array(columnar_table_data[field_name])]
            )
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
                    for s in _to_list_array(columnar_table_data[field_name])
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
                [None if s is None else _json_dumps(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert any dict/lists to json strings to avoid schema mismatches in nested objects
        if issubclass(py_type, dict | list):
            json_str_array = pa.array(
                [None if s is None else _json_dumps(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = json_str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert IP types to string
        if issubclass(py_type, IPv4Address | IPv6Address):
            str_array = pa.array(
                [None if s is None else str(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = str_array
            py_type = str
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Remove any binary columns
        if issubclass(py_type, bytes):
            drop_column_names.add(field_name)

    if len(drop_column_names) != 0:
        for column in drop_column_names:
            del columnar_table_data[column]
            if arrow_schema:
                arrow_schema = arrow_schema.remove(arrow_schema.get_field_index(str(column)))

    return pa.Table.from_pydict(columnar_table_data, schema=arrow_schema)
