import collections.abc

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.destinations import (
    databricks_batch_export,
    postgres_batch_export,
    redshift_batch_export,
    snowflake_batch_export,
)
from products.batch_exports.backend.temporal.errors import UnsupportedColumnTypeError


def _map_snowflake(schema: pa.Schema) -> snowflake_batch_export.SnowflakeTable:
    return snowflake_batch_export.SnowflakeTable.from_arrow_schema(
        schema, name="t", table_schema="s", database="d", primary_key=(), version_key=()
    )


def _map_redshift(schema: pa.Schema) -> object:
    return redshift_batch_export.get_redshift_fields_from_record_schema(schema, known_super_columns=[], use_super=False)


def _map_postgres(schema: pa.Schema) -> object:
    return postgres_batch_export.get_postgres_fields_from_record_schema(schema, known_json_columns=[])


def _map_databricks(schema: pa.Schema) -> object:
    return databricks_batch_export._get_databricks_fields_from_record_schema(schema, known_variant_columns=[])


SCHEMA_MAPPERS: list[tuple[str, collections.abc.Callable[[pa.Schema], object], collections.abc.Sequence[str]]] = [
    ("Snowflake", _map_snowflake, snowflake_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("Redshift", _map_redshift, redshift_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("PostgreSQL", _map_postgres, postgres_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("Databricks", _map_databricks, databricks_batch_export.NON_RETRYABLE_ERROR_TYPES),
]


@pytest.mark.parametrize(
    "destination, mapper, non_retryable_error_types", SCHEMA_MAPPERS, ids=[m[0] for m in SCHEMA_MAPPERS]
)
@pytest.mark.parametrize(
    "column_type",
    [pa.decimal128(38, 9), pa.map_(pa.string(), pa.string()), pa.struct([("a", pa.int64())]), pa.null()],
    ids=str,
)
def test_schema_mapping_raises_a_non_retryable_error_for_an_unsupported_column_type(
    destination: str,
    mapper: collections.abc.Callable[[pa.Schema], object],
    non_retryable_error_types: collections.abc.Sequence[str],
    column_type: pa.DataType,
) -> None:
    schema = pa.schema([pa.field("amount", column_type, nullable=True)])

    with pytest.raises(UnsupportedColumnTypeError) as exc_info:
        mapper(schema)

    assert "amount" in str(exc_info.value)
    assert destination in str(exc_info.value)
    # Each destination matches its non-retryable errors by class name, so a rename that misses
    # these lists restores the unlimited retrying this error exists to stop, and does it silently.
    assert UnsupportedColumnTypeError.__name__ in non_retryable_error_types


@pytest.mark.parametrize("column_type", [pa.date32(), pa.date64()], ids=str)
def test_snowflake_maps_a_date_column_to_date_and_reads_it_back(column_type: pa.DataType) -> None:
    table = _map_snowflake(pa.schema([pa.field("day", column_type, nullable=True)]))

    field = table["day"]
    assert field.snowflake_type_name == "DATE"
    # Every run after the one that creates the table reads the column back from the destination
    # table, so a forward mapping without a matching reverse mapping fails every later run.
    read_back = snowflake_batch_export.SnowflakeField.from_destination_field(field.to_destination_field())
    assert read_back.data_type == pa.date32()
