import json
import math
import uuid
import decimal
import hashlib
import datetime
from collections.abc import Iterator
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import orjson
import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
from dateutil import parser
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSchema

# deltalake maximum precision and scale
DEFAULT_PYARROW_DECIMAL_TYPE = pa.decimal128(38, 32)
DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES = 200 * 1024 * 1024  # 200 MB
DATE_FORMAT_BY_PARTITION_FORMAT = {
    "hour": "%Y-%m-%dT%H",
    "day": "%Y-%m-%d",
    "week": "%G-w%V",
    "month": "%Y-%m",
}


class BillingLimitsWillBeReachedException(Exception):
    pass


class DecimalPrecisionExceededException(Exception):
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
    partition_count: int | None,
    partition_size: int | None,
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
            partition_column = table.column(normalized_partition_keys[0])
            # check if the column has any non-null values before calculating min max
            if partition_column.null_count < table.num_rows:
                bounds: dict[str, int | None] = cast(dict[str, int | None], pc.min_max(partition_column).as_py())
                _min, _max = bounds["min"], bounds["max"]
                if _min is not None and _max is not None:
                    range_size = _max - _min + 1
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
                # this hash has no security impact
                # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
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
                    partition_format = "week"
                date_format = DATE_FORMAT_BY_PARTITION_FORMAT.get(
                    partition_format, DATE_FORMAT_BY_PARTITION_FORMAT["week"]
                )
                if isinstance(date, int):
                    date = datetime.datetime.fromtimestamp(date).strftime(date_format)
                elif isinstance(date, datetime.datetime | datetime.date):
                    date = date.strftime(date_format)
                elif isinstance(date, str):
                    date = parser.parse(date).strftime(date_format)
                else:
                    date = "1970-w01"
                partition_array.append(date)
    new_column = pa.array(partition_array, type=pa.string())
    logger.debug(f"append_partition_key_to_table: Partition key added with mode={mode}")
    return table.append_column(PARTITION_KEY, new_column), mode, partition_format, normalized_partition_keys


def _convert_uuid_to_string(row: dict) -> dict:
    return {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}


def json_dumps_3000(obj: Any) -> str:
    try:
        return orjson.dumps(obj).decode()
    except TypeError:
        try:
            return json.dumps(obj)
        except:
            return str(obj)


def table_from_iterator(data_iterator: Iterator[dict], schema: pa.Schema | None = None) -> pa.Table:
    batch = list(data_iterator)
    if not batch:
        return pa.Table.from_pylist([])
    processed_batch = _process_batch(list(batch), schema)
    return processed_batch


def table_from_py_list(table_data: list[Any], schema: pa.Schema | None = None) -> pa.Table:
    """
    Convert a list of Python dictionaries to a PyArrow Table.
    This is a wrapper around table_from_iterator for backward compatibility.
    """
    return table_from_iterator(iter(table_data), schema=schema)


def build_pyarrow_decimal_type(field_name: str, precision: int, scale: int) -> pa.Decimal128Type:
    if precision > 38:
        raise DecimalPrecisionExceededException(
            f"Decimal precision exceeds maximum supported precision of 38: field={field_name} precision={precision}"
        )
    return pa.decimal128(precision, scale)


def _get_max_decimal_type(field_name: str, values: list[decimal.Decimal]) -> pa.Decimal128Type:
    """Determine maximum precision and scale from all `decimal.Decimal` values.

    Returns:
        A `pa.Decimal128Type` with enough precision and scale to hold all `values`.

    Raises:
        DecimalPrecisionExceededException: If the required precision exceeds 38.
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
    return build_pyarrow_decimal_type(field_name, max_precision, max_scale)


def _python_type_to_pyarrow_type(field_name: str, type_: type, value: Any):
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
        return pa.struct(
            [pa.field(str(k), _python_type_to_pyarrow_type(field_name, type(v), v)) for k, v in value.items()]
        )
    if issubclass(type_, list) and isinstance(value, list):
        if len(value) == 0:
            return pa.list_(pa.null())
        return pa.list_(_python_type_to_pyarrow_type(field_name, type(value[0]), value[0]))
    if issubclass(type_, decimal.Decimal) and isinstance(value, decimal.Decimal):
        sign, digits, exponent = value.as_tuple()
        if isinstance(exponent, int):
            precision = len(digits)
            scale = -exponent if exponent < 0 else 0
            return build_pyarrow_decimal_type(field_name, precision, scale)
        return DEFAULT_PYARROW_DECIMAL_TYPE
    raise ValueError(f"Python type {type_} has no pyarrow mapping")


def _to_list_array(column_data: pa.Array | pa.ChunkedArray | np.ndarray[Any, np.dtype[Any]]):
    if isinstance(column_data, pa.ChunkedArray):
        return column_data.combine_chunks().tolist()
    return column_data.tolist()


def _process_batch(table_data: list[dict], schema: pa.Schema | None = None) -> pa.Table:
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
                new_field = pa.field(
                    str(field_name), _python_type_to_pyarrow_type(field_name, py_type, val), nullable=True
                )
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
                    new_field_type = _get_max_decimal_type(field_name, [x for x in all_values if x is not None])

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
                message: str | None = e.args[0] if len(e.args) else None
                if message and ("does not fit into precision" in message or "would cause data loss" in message):
                    # Upscale to the default decimal type if the schema type is too small
                    new_field_type = DEFAULT_PYARROW_DECIMAL_TYPE
                    number_arr = pa.array(all_values, type=new_field_type)
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
                    None if s is None else json_dumps_3000(s) if isinstance(s, dict | list) else s
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
                [None if s is None else json_dumps_3000(s) for s in _to_list_array(columnar_table_data[field_name])]
            )
            columnar_table_data[field_name] = json_array
            py_type = str
            unique_types_in_column = {str}
            if arrow_schema:
                arrow_schema = arrow_schema.set(field_index, arrow_schema.field(field_index).with_type(pa.string()))

        # Convert any dict/lists to json strings to avoid schema mismatches in nested objects
        if issubclass(py_type, dict | list):
            json_str_array = pa.array(
                [None if s is None else json_dumps_3000(s) for s in _to_list_array(columnar_table_data[field_name])]
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
