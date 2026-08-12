"""Assert the events model dedupes on `uuid` at every merge-capable destination.

Destination dedup itself needs a live warehouse, so the integration suites cover it
only when credentials are present. These pure-function checks guard the mapping that
decides dedup: if the events branch is dropped, events revert to append-only and a
retry re-delivers the interval.
"""

import pytest

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    _get_merge_settings as bigquery_merge_settings,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import _get_databricks_merge_config
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    _get_merge_settings as redshift_merge_settings,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    _get_merge_settings as snowflake_merge_settings,
)


def _bigquery_keys(model):
    settings = bigquery_merge_settings(model)
    if settings is None:
        return None
    return list(settings.primary_key), list(settings.version_key)


def _snowflake_keys(model):
    settings = snowflake_merge_settings(model)
    if settings is None:
        return None
    return list(settings.primary_key), list(settings.version_key)


def _databricks_keys(model):
    requires_merge, merge_key, update_key = _get_databricks_merge_config(model)
    if not requires_merge:
        return None
    return merge_key, update_key


def _redshift_keys(model):
    settings = redshift_merge_settings(model)
    if not settings.requires_merge:
        return None
    return [field[0] for field in settings.merge_key], [field[0] for field in settings.update_key]


ALL_DESTINATIONS = [_bigquery_keys, _snowflake_keys, _databricks_keys, _redshift_keys]


@pytest.mark.parametrize("get_keys", ALL_DESTINATIONS)
def test_events_model_merges_on_uuid(get_keys):
    merge_keys, version_keys = get_keys(BatchExportModel(name="events", schema=None))
    assert merge_keys == ["uuid"]
    assert version_keys == ["timestamp"]


@pytest.mark.parametrize("get_keys", ALL_DESTINATIONS)
def test_default_model_merges_on_uuid(get_keys):
    # No model means the default events export, which must dedupe the same way.
    merge_keys, version_keys = get_keys(None)
    assert merge_keys == ["uuid"]
    assert version_keys == ["timestamp"]
