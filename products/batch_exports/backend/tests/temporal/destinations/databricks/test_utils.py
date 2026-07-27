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


def test_databricks_default_fields_includes_elements_chain():
    # `elements_chain` is its own ClickHouse column, so dropping it from the field set silently loses
    # all autocapture element data from the export.
    fields = databricks_default_fields()
    assert {"expression": "elements_chain", "alias": "elements_chain"} in fields


@pytest.mark.parametrize("use_variant_type", [True, False])
def test_databricks_events_table_maps_elements_chain_to_plain_string(use_variant_type):
    # `elements_chain` is a raw serialized string, not JSON, so it must stay STRING even when
    # `properties` is exported as VARIANT.
    settings = _get_databricks_table_settings(
        model=BatchExportModel(name="events", schema=None),
        record_batch_schema=pa.schema([]),
        use_variant_type=use_variant_type,
    )
    assert ("elements_chain", "STRING") in settings.table_fields
