"""Reshape the Arrow batches a ClickHouse query returns into the types and values Delta Lake can store."""

import typing
from collections.abc import Collection

import pyarrow as pa
import pyarrow.compute as pc
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableApplicationError, NonReportableError


class UnstorableIntegerError(NonReportableError):
    """A column holds a whole number too large for the signed integer types Delta Lake has."""

    def __init__(self, column: str) -> None:
        super().__init__(
            f'Column "{column}" has whole numbers larger than {2**63 - 1}, which is the largest a '
            f"materialized table can store. Wrap the column in toString() to store it as text."
        )
        self.column = column


def _transform_date_and_datetimes(batch: pa.RecordBatch, types: list[tuple[str, str]]) -> pa.RecordBatch:
    """Transform date/datetimes from ClickHouse UInt representations back to proper types."""
    new_columns: list[pa.Array] = []
    new_fields: list[pa.Field] = []

    types_to_transform = ["Date", "Date32", "DateTime", "DateTime64"]
    for column_name, type in types:
        field = batch.schema.field(column_name)
        column = batch.column(column_name)

        if not any(t.lower() in type.lower() for t in types_to_transform) or pa.types.is_date(field.type):
            new_columns.append(column)
            new_fields.append(field)
            continue

        # Handle array/list types (e.g., Array(DateTime))
        if pa.types.is_list(field.type):
            if "datetime" in type.lower():
                list_element_type: pa.DataType = pa.timestamp("us", tz="UTC")
                list_type = pa.list_(list_element_type)
                list_field = field.with_type(list_type)
                list_int64 = pc.cast(column, pa.list_(pa.int64()))
                list_timestamp_s = pc.cast(list_int64, pa.list_(pa.timestamp("s")))
                list_column = pc.cast(list_timestamp_s, list_type)
            else:
                list_element_type = pa.date32()
                list_type = pa.list_(list_element_type)
                list_field = field.with_type(list_type)
                list_int32 = pc.cast(column, pa.list_(pa.int32()))
                list_column = pc.cast(list_int32, list_type)

            new_fields.append(list_field)
            new_columns.append(list_column)
            continue

        # Handle scalar types
        if "datetime64" in type.lower() and pa.types.is_timestamp(field.type):
            new_field: pa.Field = field.with_type(pa.timestamp("us", tz="UTC"))
            new_column = pc.cast(column, new_field.type)
        elif "datetime" in type.lower():
            new_field = field.with_type(pa.timestamp("us", tz="UTC"))
            int64_col = pc.cast(column, pa.int64())
            seconds_col = pc.cast(int64_col, pa.timestamp("s"))
            new_column = pc.cast(seconds_col, new_field.type)
        else:
            new_field = field.with_type(pa.date32())
            int32_col = pc.cast(column, pa.int32())
            new_column = pc.cast(int32_col, new_field.type)

        new_fields.append(new_field)
        new_columns.append(new_column)

    new_metadata: dict[str | bytes, str | bytes] | None = (
        typing.cast(dict[str | bytes, str | bytes], dict(batch.schema.metadata)) if batch.schema.metadata else None
    )

    return pa.RecordBatch.from_arrays(new_columns, schema=pa.schema(new_fields, metadata=new_metadata))


def _nullable_type(arrow_type: pa.DataType) -> pa.DataType:
    if pa.types.is_large_list(arrow_type):
        return pa.large_list(_nullable_field(arrow_type.value_field))

    if pa.types.is_list(arrow_type):
        return pa.list_(_nullable_field(arrow_type.value_field))

    if pa.types.is_struct(arrow_type):
        return pa.struct([_nullable_field(field) for field in arrow_type])

    if pa.types.is_map(arrow_type):
        # A map built from types has a nullable value and a non-nullable key, which Arrow requires.
        return pa.map_(
            _nullable_type(arrow_type.key_type), _nullable_type(arrow_type.item_type), arrow_type.keys_sorted
        )

    return arrow_type


def _nullable_field(field: pa.Field) -> pa.Field:
    return field.with_type(_nullable_type(field.type)).with_nullable(True)


def _force_nullable(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Mark every column nullable so batch schemas don't diverge across delta commits.

    ClickHouse emits non-nullable columns for expressions, constants, concat()/toString(),
    and non-Nullable source columns. When such a query spans more than one batch, the first
    batch's overwrite pins a non-nullable delta schema and the later append routes through
    delta-rs's DataFusion writer to reconcile schemas. DataFusion lowercases identifiers and
    then fails to resolve case-sensitive columns, e.g. "No field named userid. ... Did you
    mean 'userId'?" — breaking any column with uppercase characters. Pinning every column to
    nullable keeps each batch's schema identical to the first overwrite, so the append never
    triggers that path and camelCase column names survive.

    Nested children are relaxed too. A list element, struct field or map value that is
    non-nullable in the first batch and nullable in a later one is accepted by the append, but
    compaction then fails because it cannot cast the nullable child back to non-nullable.
    """
    nullable_schema = pa.schema(
        [_nullable_field(field) for field in batch.schema],
        metadata=typing.cast("dict[bytes | str, bytes | str] | None", batch.schema.metadata),
    )
    return batch.cast(nullable_schema)


class UnstorableDecimalError(NonReportableApplicationError):
    """A nested column holds a decimal with more digits than the 128-bit decimals Delta Lake has.

    Non-retryable here rather than in the workflow's retry policy, so that a retry of the same
    query does not repeat the read and the writes before it fails on the same value again.
    """

    def __init__(self, column: str) -> None:
        super().__init__(
            f'Column "{column}" has decimal values with more than 38 digits, which is the most a '
            f"materialized table can store. Round the values, or wrap the column in toString() to store it as text.",
            type="UnstorableDecimalError",
            non_retryable=True,
        )
        self.column = column


DELTA_MAX_DECIMAL_PRECISION = 38


def _delta_decimal_type(arrow_type: pa.DataType) -> pa.DataType:
    """The type Delta Lake stores this as. Unchanged unless a decimal wider than 128 bits is in it."""
    if pa.types.is_decimal256(arrow_type):
        if arrow_type.precision <= DELTA_MAX_DECIMAL_PRECISION:
            return pa.decimal128(arrow_type.precision, arrow_type.scale)
        return pa.decimal128(DELTA_MAX_DECIMAL_PRECISION, min(arrow_type.scale, DELTA_MAX_DECIMAL_PRECISION - 1))

    if pa.types.is_large_list(arrow_type):
        return pa.large_list(_delta_decimal_field(arrow_type.value_field))

    if pa.types.is_list(arrow_type):
        return pa.list_(_delta_decimal_field(arrow_type.value_field))

    if pa.types.is_struct(arrow_type):
        return pa.struct([_delta_decimal_field(field) for field in arrow_type])

    if pa.types.is_map(arrow_type):
        return pa.map_(
            _delta_decimal_type(arrow_type.key_type), _delta_decimal_type(arrow_type.item_type), arrow_type.keys_sorted
        )

    return arrow_type


def _delta_decimal_field(field: pa.Field) -> pa.Field:
    return field.with_type(_delta_decimal_type(field.type))


def _transform_unsupported_decimals(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Transform decimal columns wider than 128 bits, at any depth, to types supported by Delta Lake."""
    schema = batch.schema
    target_fields = [_delta_decimal_field(field) for field in schema]
    if all(target.type.equals(field.type) for target, field in zip(target_fields, schema)):
        return batch

    precision = DELTA_MAX_DECIMAL_PRECISION
    scale = DELTA_MAX_DECIMAL_PRECISION - 1

    new_columns: list[pa.Array] = []
    new_fields: list[pa.Field] = []

    for field, target in zip(schema, target_fields):
        col = batch[field.name]
        if target.type.equals(field.type):
            new_fields.append(field)
            new_columns.append(col)
        elif pa.types.is_decimal(field.type):
            try:
                cast_col = pc.cast(col, target.type)
                new_fields.append(target)
                new_columns.append(cast_col)
            except Exception:
                reduced_decimal_type = pa.decimal128(precision, scale)
                # signals to the type checker that the underlying type is a pa.StringArray
                string_col = typing.cast(pa.StringArray, pc.cast(col, pa.string()))
                truncated = pc.utf8_slice_codeunits(string_col, 0, precision)
                cast_reduced = pc.cast(truncated, reduced_decimal_type)
                new_fields.append(field.with_type(reduced_decimal_type))
                new_columns.append(cast_reduced)
        else:
            try:
                new_columns.append(pc.cast(col, target.type))
            except pa.ArrowInvalid as err:
                raise UnstorableDecimalError(field.name) from err
            new_fields.append(target)

    new_metadata: dict[str | bytes, str | bytes] | None = (
        typing.cast(dict[str | bytes, str | bytes], dict(schema.metadata)) if schema.metadata else None
    )

    return pa.RecordBatch.from_arrays(new_columns, schema=pa.schema(new_fields, metadata=new_metadata))


# A slice that holds invalid UTF-8 is halved until its strings fit in this many bytes, and only
# then decoded in Python. The decode holds the slice as bytes and as str objects at once, so this
# bounds that memory. A single value is decoded whole, so its memory scales with one value that
# ClickHouse already returned.
UTF8_REPAIR_MAX_BYTES = 1024 * 1024


def _is_valid_utf8(array: pa.Array | pa.RecordBatch) -> bool:
    try:
        array.validate(full=True)
    except pa.ArrowInvalid as error:
        if "Invalid UTF8 sequence" not in str(error):
            raise
        return False
    return True


def _collect_repaired_strings(array: pa.Array, pieces: list[pa.Array]) -> None:
    if _is_valid_utf8(array):
        pieces.append(array)
        return
    string_bytes = pc.sum(pc.binary_length(typing.cast(pa.StringArray, array))).as_py() or 0
    if len(array) > 1 and string_bytes > UTF8_REPAIR_MAX_BYTES:
        middle = len(array) // 2
        _collect_repaired_strings(array.slice(0, middle), pieces)
        _collect_repaired_strings(array.slice(middle), pieces)
        return
    binary_type = pa.large_binary() if pa.types.is_large_string(array.type) else pa.binary()
    raw = typing.cast(list[bytes | None], array.cast(binary_type).to_pylist())
    pieces.append(
        pa.array([None if value is None else value.decode("utf-8", errors="replace") for value in raw], type=array.type)
    )


def _replace_invalid_utf8_in_strings(array: pa.Array) -> pa.Array:
    pieces: list[pa.Array] = []
    _collect_repaired_strings(array, pieces)
    return pa.concat_arrays(pieces)


def _utf8_repaired(array: pa.Array) -> pa.Array:
    if _is_valid_utf8(array):
        return array

    arrow_type = array.type
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return _replace_invalid_utf8_in_strings(array)

    # pyarrow cannot rebuild a sliced nested array with a null mask, so the rebuild starts from an
    # unsliced copy. This copy happens only for a column that holds invalid UTF-8.
    array = pa.concat_arrays([array])
    if pa.types.is_large_list(arrow_type):
        large_list = typing.cast(pa.LargeListArray, array)
        return pa.LargeListArray.from_arrays(
            large_list.offsets, _utf8_repaired(large_list.values), type=arrow_type, mask=large_list.is_null()
        )
    if pa.types.is_list(arrow_type):
        list_array = typing.cast(pa.ListArray, array)
        return pa.ListArray.from_arrays(
            list_array.offsets, _utf8_repaired(list_array.values), type=arrow_type, mask=list_array.is_null()
        )
    if pa.types.is_struct(arrow_type):
        struct_array = typing.cast(pa.StructArray, array)
        return pa.StructArray.from_arrays(
            [_utf8_repaired(struct_array.field(index)) for index in range(arrow_type.num_fields)],
            fields=list(arrow_type),
            mask=struct_array.is_null(),
        )
    if pa.types.is_map(arrow_type):
        map_array = typing.cast(pa.MapArray, array)
        # The stubs accept a type only with an entries struct, a form pyarrow itself rejects.
        return pa.MapArray.from_arrays(  # type: ignore[call-overload]
            map_array.offsets,
            _utf8_repaired(map_array.keys),
            _utf8_repaired(map_array.items),
            type=arrow_type,
            mask=map_array.is_null(),
        )
    return array


class InvalidUtf8KeyError(NonReportableApplicationError):
    """An incremental or unique key column holds text that is not valid UTF-8.

    The replacement character can turn two different keys into one, and deltalite refuses to
    upsert the raw bytes, so the run fails before it writes anything.
    """

    def __init__(self, column: str) -> None:
        super().__init__(
            f'Key column "{column}" has text that is not valid UTF-8, so a materialized table cannot use it as a '
            f"key. To key on its hex form, write hex({column}) AS {column} in the query.",
            type="InvalidUtf8KeyError",
            non_retryable=True,
        )
        self.column = column


def _replace_invalid_utf8(batch: pa.RecordBatch, key_columns: Collection[str] = ()) -> pa.RecordBatch:
    """Replace byte sequences that are not valid UTF-8 in string values, at any depth, with U+FFFD.

    A ClickHouse String holds arbitrary bytes, and the Arrow stream sends it as an Arrow string
    without a check. Parquet stores the bytes as they are, but deltalake, DuckDB and Trino then
    refuse to read the file. The column keeps its string type so that the table schema does not
    depend on the data in one batch.

    A key column with invalid UTF-8 fails the run instead. The replacement can turn two different
    keys into the same string, which would merge two rows on a unique key, or move an incremental
    watermark past rows that the next run must still read.
    """
    if _is_valid_utf8(batch):
        return batch
    for column in key_columns:
        if column in batch.schema.names and not _is_valid_utf8(batch.column(column)):
            raise InvalidUtf8KeyError(column)
    repaired: list[pa.Array] = []
    for field, array in zip(batch.schema, batch.columns):
        repaired_array = _utf8_repaired(array)
        # The repair returns a type it does not rebuild, such as a dictionary of strings, unchanged.
        # Writing it would store a file that Delta readers refuse.
        if not _is_valid_utf8(repaired_array):
            raise ApplicationError(
                f'Column "{field.name}" of type {field.type} still has invalid UTF-8 after the repair.',
                type="UnrepairedUtf8Error",
                non_retryable=True,
            )
        repaired.append(repaired_array)
    return pa.RecordBatch.from_arrays(repaired, schema=batch.schema)


_SIGNED_EQUIVALENT_BY_BIT_WIDTH = {8: pa.int16(), 16: pa.int32(), 32: pa.int64(), 64: pa.int64()}


def _signed_equivalent(arrow_type: pa.DataType) -> pa.DataType:
    """The type Delta Lake stores this as. Unchanged unless an unsigned integer is in it."""
    if pa.types.is_unsigned_integer(arrow_type):
        return _SIGNED_EQUIVALENT_BY_BIT_WIDTH[arrow_type.bit_width]

    if pa.types.is_large_list(arrow_type):
        return pa.large_list(_signed_equivalent_field(arrow_type.value_field))

    if pa.types.is_list(arrow_type):
        return pa.list_(_signed_equivalent_field(arrow_type.value_field))

    if pa.types.is_struct(arrow_type):
        return pa.struct([_signed_equivalent_field(field) for field in arrow_type])

    if pa.types.is_map(arrow_type):
        return pa.map_(_signed_equivalent(arrow_type.key_type), _signed_equivalent(arrow_type.item_type))

    return arrow_type


def _signed_equivalent_field(field: pa.Field) -> pa.Field:
    return field.with_type(_signed_equivalent(field.type))


def _transform_unsigned_integers(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Cast unsigned integer columns to the signed types Delta Lake stores them as."""
    signed_fields = [_signed_equivalent_field(field) for field in batch.schema]
    if all(signed.type.equals(field.type) for signed, field in zip(signed_fields, batch.schema)):
        return batch

    columns: list[pa.Array] = []
    for field in signed_fields:
        try:
            columns.append(pc.cast(batch.column(field.name), field.type))
        except pa.ArrowInvalid as err:
            raise UnstorableIntegerError(field.name) from err

    signed_schema = pa.schema(
        signed_fields,
        metadata=typing.cast("dict[bytes | str, bytes | str] | None", batch.schema.metadata),
    )
    return pa.RecordBatch.from_arrays(columns, schema=signed_schema)
