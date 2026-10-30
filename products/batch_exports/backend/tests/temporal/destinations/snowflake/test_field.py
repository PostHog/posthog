import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeDestinationField,
    SnowflakeField,
    SnowflakeFieldDescriptor,
)
from products.batch_exports.backend.temporal.utils import JsonType


@pytest.mark.parametrize(
    "data_type,ddl,destination_field,description",
    [
        # Snowflake reports a 'NUMBER(38, 2)' column as 'FIXED' with precision 38 and scale 2.
        (
            pa.decimal128(38, 2),
            "NUMBER(38, 2)",
            SnowflakeDestinationField("value", "FIXED", True, 38, 2),
            "NUMBER(38,2)",
        ),
        (pa.int64(), "INTEGER", SnowflakeDestinationField("value", "FIXED", False, 38, 0), "NUMBER(38,0)"),
        (pa.uuid(), "UUID", SnowflakeDestinationField("value", "UUID", True), "UUID"),
        (pa.binary(), "BINARY", SnowflakeDestinationField("value", "BINARY", False), "BINARY(8388608)"),
        (pa.string(), "STRING", SnowflakeDestinationField("value", "TEXT", True), "VARCHAR(16777216) COLLATE 'en-ci'"),
        (pa.float64(), "FLOAT", SnowflakeDestinationField("value", "FLOAT", True), "FLOAT"),
        (pa.bool_(), "BOOLEAN", SnowflakeDestinationField("value", "BOOLEAN", False), "BOOLEAN"),
        (pa.date32(), "DATE", SnowflakeDestinationField("value", "DATE", True), "DATE"),
        (
            pa.timestamp("ms", tz="UTC"),
            "TIMESTAMP",
            SnowflakeDestinationField("value", "TIMESTAMP_NTZ", True),
            "TIMESTAMP_NTZ(9)",
        ),
        (
            pa.timestamp("ms", tz="UTC"),
            "TIMESTAMP",
            SnowflakeDestinationField("value", "TIMESTAMP_LTZ", True),
            "TIMESTAMP_LTZ(9)",
        ),
        (
            pa.timestamp("ms", tz="UTC"),
            "TIMESTAMP",
            SnowflakeDestinationField("value", "TIMESTAMP_TZ", True),
            "TIMESTAMP_TZ(9)",
        ),
        (pa.list_(pa.string()), "ARRAY", SnowflakeDestinationField("value", "ARRAY", True), "ARRAY"),
        (JsonType(), "VARIANT", SnowflakeDestinationField("value", "VARIANT", True), "VARIANT"),
    ],
)
def test_field_maps_to_snowflake_type_and_reads_back(
    data_type: pa.DataType, ddl: str, destination_field: SnowflakeDestinationField, description: str
) -> None:
    field = SnowflakeField.from_arrow_field(pa.field("value", data_type, nullable=destination_field.is_nullable))

    assert field.snowflake_type_ddl == ddl
    parsed = SnowflakeDestinationField.from_field_descriptor(
        SnowflakeFieldDescriptor(name="value", data_type=description, is_nullable=destination_field.is_nullable)
    )
    assert parsed == destination_field
    restored = SnowflakeField.from_destination_field(parsed)
    assert restored == field
    assert restored.nullable == field.nullable
    assert SnowflakeField.from_destination_field(field.to_destination_field()) == field
