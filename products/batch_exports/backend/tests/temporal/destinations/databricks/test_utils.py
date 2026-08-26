import datetime as dt

import pytest

import pyarrow as pa

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
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
    # The events branch keys off column names only, so the types here are arbitrary.
    return pa.schema([pa.field(name, pa.string()) for name in column_names])


def _events_table_field_names(staged_column_names: list[str]) -> list[str]:
    table_fields, _, _ = _get_databricks_table_settings(
        model=BatchExportModel(name="events", schema=None),
        record_batch_schema=_staged_events_schema(staged_column_names),
        use_variant_type=True,
    )
    return [name for name, _ in table_fields]


def test_events_table_fields_cover_every_exported_field():
    # The fields we query and the table columns we create are two separate literals, so adding to
    # one without the other silently drops the column from the user's table.
    exported = [field["alias"] for field in databricks_default_fields()]
    # `_inserted_at` only tracks progress and is never exported.
    expected = sorted(alias for alias in exported if alias != "_inserted_at")

    assert sorted(_events_table_field_names(exported)) == expected


def test_events_table_fields_exclude_columns_missing_from_staged_data():
    # A run that staged its data before `created_at` was added has no such column to copy.
    staged = [field["alias"] for field in databricks_default_fields() if field["alias"] != "created_at"]

    assert "created_at" not in _events_table_field_names(staged)
