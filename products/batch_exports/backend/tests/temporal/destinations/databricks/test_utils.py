import datetime as dt

import pytest

import pyarrow as pa

from products.batch_exports.backend.service import BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    _events_table_fields,
    _get_databricks_table_settings,
    _get_long_running_query_timeout,
    databricks_default_fields,
)


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
        model=BatchExportModel(name="events", schema=schema),
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

    assert sorted(name for name, _ in _events_table_fields("VARIANT")) == exported


def test_events_table_fields_drop_columns_missing_from_staged_data():
    # A run that staged its data before `created_at` was added has no such column to copy, so
    # dropping it keeps the copy working instead of wedging the run on a retry loop.
    staged = [field["alias"] for field in databricks_default_fields() if field["alias"] != "created_at"]

    assert "created_at" not in _events_table_field_names(staged, schema=None)


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
