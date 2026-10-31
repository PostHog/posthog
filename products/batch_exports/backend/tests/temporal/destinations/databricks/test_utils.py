import datetime as dt

import pytest

import pyarrow as pa

from products.batch_exports.backend.service import (
    BatchExportEventsCustomModel,
    BatchExportEventsModel,
    BatchExportHogQLModel,
    BatchExportSchema,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    _events_table_fields,
    _get_databricks_table_settings,
    _get_long_running_query_timeout,
    databricks_default_fields,
)
from products.batch_exports.backend.temporal.utils import JsonType


@pytest.mark.parametrize(
    "data_interval_start, data_interval_end, expected_timeout",
    [
        # when no data interval start is provided, we use the max timeout of 6 hours
        (None, dt.datetime(2025, 1, 1, 12, 0, 0), 6 * 60 * 60),
        # when the interval is 1 day we use the max timeout of 6 hours
        (dt.datetime(2025, 1, 1, 0, 0, 0), dt.datetime(2025, 1, 2, 0, 0, 0), 6 * 60 * 60),
        # when the interval is 1 hour we expect the timeout to be 2 hours (as we multiply the interval by 2 for now while we are in beta testing)
        (dt.datetime(2025, 1, 1, 12, 0, 0), dt.datetime(2025, 1, 1, 13, 0, 0), 2 * 60 * 60),
        # when interval is 5 minutes, we expect the timeout to be the minimum timeout of 30 minutes
        (dt.datetime(2025, 1, 1, 12, 0, 0), dt.datetime(2025, 1, 1, 12, 5, 0), 30 * 60),
    ],
)
def test_get_long_running_query_timeout(data_interval_start, data_interval_end, expected_timeout):
    assert _get_long_running_query_timeout(data_interval_start, data_interval_end) == expected_timeout


def _staged_events_schema(column_names: list[str]) -> pa.Schema:
    # Only the column names are asserted on below, so the types here are arbitrary.
    return pa.schema([pa.field(name, pa.string()) for name in column_names])


def _events_table_field_names(staged_column_names: list[str], schema: BatchExportSchema | None) -> list[str]:
    table_fields, _, _ = _get_databricks_table_settings(
        model=BatchExportEventsCustomModel(schema=schema) if schema is not None else BatchExportEventsModel(),
        record_batch_schema=_staged_events_schema(staged_column_names),
        use_variant_type=True,
    )
    return [name for name, _ in table_fields]


def test_events_table_fields_match_the_exported_fields():
    # The fields we query and the table columns we create are two separate literals. Adding to the
    # first alone drops the column from the user's table; adding to the second alone builds a
    # CREATE TABLE and a COPY INTO naming a column the staged data has no value for.
    # `_inserted_at` only tracks progress and is never exported.
    exported = sorted(field["alias"] for field in databricks_default_fields() if field["alias"] != "_inserted_at")

    assert "person_id" in exported
    assert sorted(name for name, _ in _events_table_fields("VARIANT")) == exported


@pytest.mark.parametrize("missing_column", ["created_at", "person_id"])
def test_events_table_fields_drop_columns_missing_from_staged_data(missing_column: str) -> None:
    # A run that staged its data before a column was added has no such column to copy, so
    # dropping it keeps the copy working instead of wedging the run on a retry loop.
    staged = [field["alias"] for field in databricks_default_fields() if field["alias"] != missing_column]

    assert missing_column not in _events_table_field_names(staged, schema=None)


def test_events_table_fields_follow_a_custom_schema():
    # A custom schema stages only the columns it selects, so the table has to follow the staged
    # data. Starting from the default events columns instead loses every column outside them, such
    # as `browser` here, and names columns the staged files have no value for.
    schema: BatchExportSchema = {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
        ],
        "values": {"hogql_val_0": "$browser"},
    }

    assert _events_table_field_names(["event", "browser"], schema=schema) == ["event", "browser"]


@pytest.mark.parametrize(
    "field_name, pa_type, expected_databricks_type",
    [
        ("col", pa.string(), "STRING"),
        ("col", JsonType(), "STRING"),
        ("properties", pa.string(), "VARIANT"),
        ("col", pa.binary(), "BINARY"),
        ("col", pa.int32(), "INTEGER"),
        ("col", pa.uint8(), "INTEGER"),
        ("col", pa.int64(), "BIGINT"),
        ("col", pa.uint64(), "BIGINT"),
        ("col", pa.float32(), "FLOAT"),
        ("col", pa.float64(), "DOUBLE"),
        ("col", pa.bool_(), "BOOLEAN"),
        ("col", pa.timestamp("us", tz="UTC"), "TIMESTAMP"),
        ("col", pa.date32(), "DATE"),
        ("col", pa.date64(), "DATE"),
        ("col", pa.decimal128(38, 2), "DECIMAL(38, 2)"),
        ("col", pa.decimal256(10, 0), "DECIMAL(10, 0)"),
        ("col", pa.list_(pa.string()), "ARRAY<STRING>"),
        ("col", pa.list_(pa.int64()), "ARRAY<BIGINT>"),
    ],
)
def test_hogql_table_fields_map_arrow_types(
    field_name: str, pa_type: pa.DataType, expected_databricks_type: str
) -> None:
    # A HogQL query stages whatever Arrow types its columns produce. A type without a mapping makes
    # the insert activity raise on every retry, so the run never lands.
    table_fields, _, _ = _get_databricks_table_settings(
        model=BatchExportHogQLModel(query="SELECT 1", user_id=1, modifiers={}),
        record_batch_schema=pa.schema([pa.field(field_name, pa_type)]),
        use_variant_type=True,
    )

    assert table_fields == [(field_name, expected_databricks_type)]


@pytest.mark.parametrize("pa_type", [pa.decimal256(76, 0), pa.list_(pa.decimal256(76, 0))])
def test_hogql_table_fields_reject_unsupported_arrow_types(pa_type: pa.DataType) -> None:
    with pytest.raises(TypeError, match=r"Unsupported type in field 'col': '.*decimal256\(76, 0\)"):
        _get_databricks_table_settings(
            model=BatchExportHogQLModel(query="SELECT 1", user_id=1, modifiers={}),
            record_batch_schema=pa.schema([pa.field("col", pa_type)]),
            use_variant_type=True,
        )
