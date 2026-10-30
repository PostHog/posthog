import pyarrow as pa

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeDestinationField,
    SnowflakeField,
)


def test_decimal_field_maps_to_number_and_reads_back_as_decimal() -> None:
    field = SnowflakeField.from_arrow_field(pa.field("amount", pa.decimal128(38, 2)))

    assert field.snowflake_type_ddl == "NUMBER(38, 2)"
    # Snowflake reports a 'NUMBER(38, 2)' column as 'FIXED' with precision 38 and scale 2.
    assert SnowflakeField.from_destination_field(SnowflakeDestinationField("amount", "FIXED", True, 38, 2)) == field
    assert SnowflakeField.from_destination_field(field.to_destination_field()) == field
