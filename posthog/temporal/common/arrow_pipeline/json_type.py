"""An Arrow extension type for columns that hold JSON documents as strings."""

import re
import typing
import collections.abc

import orjson
import pyarrow as pa

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)


class JsonScalar(pa.ExtensionScalar):
    """Represents a JSON binary string."""

    def as_py(self, *, maps_as_pydicts: typing.Literal["lossy", "strict"] | None = None) -> dict | None:
        """Try to convert value to Python representation.

        We attempt to decode the value returned by `as_py` as JSON. However, to do so safely we must
        ensure the value is a valid UTF-8 string. We try to take care of the following scenarios:
        * Unescaped whitespace characters (e.g. \n).
        * Unescaped surrogates without a pair.
        * Escaped surrogates without a pair.
        * Not a JSON document (we assume it's a string and quote it).

        If all else fails, we will log the offending value and re-raise the decoding error.
        """
        if self.value:
            value = self.value.as_py()

            if re.search("([\t\n\r\f\v])", value):
                value = value.encode("unicode-escape").decode("utf-8")

            if not value:
                return None

            json_bytes = value.encode("utf-8", "replace")

            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                pass

            json_bytes = json_bytes.decode("raw-unicode-escape").encode("utf-8", "replace")

            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                pass

            if isinstance(value, str) and len(value) > 0 and not value.startswith("{") and not value.endswith("}"):
                # Handles non-valid JSON strings like `'"$set": "Something"'` by quoting them.
                value = f'"{value}"'

            json_bytes = value.encode("utf-8", "replace").decode("raw-unicode-escape").encode("utf-8", "replace")
            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                LOGGER.exception("Failed to decode with orjson: %s", value)
                raise

        else:
            return None


class JsonType(pa.ExtensionType):
    """Type for JSON binary strings."""

    def __init__(self):
        super().__init__(pa.string(), "json")

    def __arrow_ext_serialize__(self):
        return b""

    def __hash__(self):
        return pa.DataType.__hash__(self)

    @classmethod
    def __arrow_ext_deserialize__(self, storage_type, serialized):
        return JsonType()

    def __arrow_ext_scalar_class__(self):
        return JsonScalar


def cast_record_batch_json_columns(
    record_batch: pa.RecordBatch,
    json_columns: collections.abc.Iterable[str],
) -> pa.RecordBatch:
    """Cast json_columns in record_batch to JsonType.

    We return a new RecordBatch with any json_columns replaced by fields casted to JsonType.
    Casting is not copying the underlying array buffers, so memory usage does not increase when creating
    the new array or the new record batch.
    """
    column_names = set(record_batch.column_names)
    intersection = column_names & set(json_columns)

    casted_arrays = []
    for array in record_batch.select(intersection):  # type: ignore
        if pa.types.is_string(array.type):
            casted_array = array.cast(JsonType())
            casted_arrays.append(casted_array)

    remaining_column_names = list(column_names - intersection)
    return pa.RecordBatch.from_arrays(
        record_batch.select(remaining_column_names).columns + casted_arrays,
        names=remaining_column_names + list(intersection),
    )


def cast_record_batch_schema_json_columns(
    schema: pa.Schema,
    json_columns: collections.abc.Iterable[str],
) -> pa.Schema:
    column_names = set(schema.names)
    intersection = column_names & set(json_columns)
    new_fields = []

    for field in schema:
        if field.name not in intersection or not pa.types.is_string(field.type):
            new_fields.append(field)
            continue

        casted_field = field.with_type(JsonType())
        new_fields.append(casted_field)

    new_schema = pa.schema(new_fields)

    return new_schema
