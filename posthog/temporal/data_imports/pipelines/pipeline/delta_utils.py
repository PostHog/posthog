"""
Delta Lake compatibility utilities.

Replaces DLT's ensure_delta_compatible_arrow_schema with a simplified version.
"""

import pyarrow as pa


def ensure_delta_compatible_arrow_schema(schema: pa.Schema) -> pa.Schema:
    """Convert PyArrow schema to be compatible with Delta Lake.

    Compatible with dlt.common.libs.deltalake.ensure_delta_compatible_arrow_schema

    Delta Lake has restrictions on certain types:
    - Nanosecond timestamps must be converted to microseconds
    - Large string/binary types must be converted to standard types
    - Duration types are not supported

    Args:
        schema: PyArrow schema to convert

    Returns:
        Delta Lake-compatible PyArrow schema
    """
    new_fields = []
    for field in schema:
        new_type = _convert_type_for_delta(field.type)
        new_fields.append(pa.field(field.name, new_type, nullable=field.nullable, metadata=field.metadata))
    return pa.schema(new_fields, metadata=schema.metadata)


def _convert_type_for_delta(arrow_type: pa.DataType) -> pa.DataType:
    """Convert individual PyArrow type for Delta Lake compatibility.

    Args:
        arrow_type: PyArrow type to convert

    Returns:
        Delta Lake-compatible PyArrow type
    """
    # Nanosecond timestamps -> microseconds
    if pa.types.is_timestamp(arrow_type):
        if arrow_type.unit == "ns":
            return pa.timestamp("us", tz=arrow_type.tz)
        if arrow_type.unit == "s" or arrow_type.unit == "ms":
            # Upscale to microseconds
            return pa.timestamp("us", tz=arrow_type.tz)

    # Large types -> standard types
    if pa.types.is_large_string(arrow_type):
        return pa.string()
    if pa.types.is_large_binary(arrow_type):
        return pa.binary()
    if pa.types.is_large_list(arrow_type):
        return pa.list_(_convert_type_for_delta(arrow_type.value_type))

    # Duration types -> not supported, convert to int64 (total microseconds)
    if pa.types.is_duration(arrow_type):
        # Delta Lake doesn't support duration, convert to int64 microseconds
        return pa.int64()

    # Handle nested types recursively
    if pa.types.is_list(arrow_type):
        return pa.list_(_convert_type_for_delta(arrow_type.value_type))

    if pa.types.is_struct(arrow_type):
        new_fields = []
        for field in arrow_type:
            new_type = _convert_type_for_delta(field.type)
            new_fields.append(pa.field(field.name, new_type, nullable=field.nullable, metadata=field.metadata))
        return pa.struct(new_fields)

    if pa.types.is_map(arrow_type):
        return pa.map_(
            _convert_type_for_delta(arrow_type.key_type), _convert_type_for_delta(arrow_type.item_type)
        )

    # Return type as-is if no conversion needed
    return arrow_type
