"""
Entry points and patch targets for tests in other products.

Production callers use ``facade/api.py`` and ``facade/temporal.py``. These helpers exist so a test in another product
can drive the incremental write and the HogQL compile without reaching into ``backend/temporal/``.

The ``patch_*`` helpers stub the side effects a saved-query or endpoint request reaches inside this product. An
outside test that names a ``backend/logic/`` module by dotted path makes `hogli product:lint` watch that module
as contract surface, so every change to it re-runs the full backend suite. Keeping the dotted paths here keeps
``backend/logic/`` internal, and ``test_facade_testing_patches.py`` fails in this product's suite when one goes stale.

Imports the activity modules, so it must only be imported off the ``django.setup()`` path.
"""

from typing import TYPE_CHECKING, Any, Optional

from unittest.mock import patch

import pyarrow as pa

from products.data_modeling.backend.temporal.activities import incremental_write
from products.data_modeling.backend.temporal.activities.materialize_view_managed_warehouse import (
    _compile_hogql_for_ducklake,
)

if TYPE_CHECKING:
    from unittest.mock import MagicMock, _patch

__all__ = [
    "PATCH_HELPERS",
    "check_unique_key",
    "compile_hogql_for_ducklake",
    "patch_access_check",
    "patch_column_describe_query",
    "patch_column_describe_retry_sleep",
    "patch_dag_reconcile",
    "patch_dag_schedule_reconcile",
    "patch_deletion_dependents_check",
    "patch_frequency_target_apply",
    "patch_managed_warehouse_shadow_enabled",
    "patch_node_type_update",
    "patch_reconcile_capture",
    "patch_refresh_floor_flag",
    "patch_saved_query_dag_sync",
    "patch_saved_query_sql",
    "patch_temporal_client",
    "upsert_batch",
]

_LOGIC = "products.data_modeling.backend.logic"


def patch_temporal_client(**kwargs: Any) -> "_patch[MagicMock]":
    """The Temporal client that starts a materialization run."""
    return patch(f"{_LOGIC}.node_materialization.sync_connect", **kwargs)


def patch_managed_warehouse_shadow_enabled(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.node_materialization.is_managed_warehouse_shadow_enabled", **kwargs)


def patch_access_check(**kwargs: Any) -> "_patch[MagicMock]":
    """The object access check a run makes before it materializes a node."""
    return patch(f"{_LOGIC}.node_materialization.UserAccessControl.check_access_level_for_object", **kwargs)


def patch_dag_reconcile(**kwargs: Any) -> "_patch[MagicMock]":
    """The schedule reconcile that a cadence or node change triggers for its DAG."""
    return patch(f"{_LOGIC}.schedule_reconcile.maybe_reconcile_dag", **kwargs)


def patch_dag_schedule_reconcile(**kwargs: Any) -> "_patch[MagicMock]":
    """The Temporal schedule writes inside a DAG reconcile."""
    return patch(f"{_LOGIC}.schedule_reconcile.reconcile_dag_schedules", **kwargs)


def patch_reconcile_capture(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.schedule_reconcile.ph_background_capture", **kwargs)


def patch_frequency_target_apply(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.schedule_reconcile.apply_saved_query_frequency_target", **kwargs)


def patch_column_describe_query(**kwargs: Any) -> "_patch[MagicMock]":
    """The ClickHouse DESCRIBE that infers a saved query's columns."""
    return patch(f"{_LOGIC}.describe_columns.sync_execute", **kwargs)


def patch_column_describe_retry_sleep(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.describe_columns.sleep", **kwargs)


def patch_refresh_floor_flag(**kwargs: Any) -> "_patch[MagicMock]":
    """The feature flag that turns on the plan-based minimum refresh interval."""
    return patch(f"{_LOGIC}.refresh_floor.feature_enabled_or_false", **kwargs)


def patch_saved_query_dag_sync(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.saved_query_dag_sync.sync_saved_query_to_dag", **kwargs)


def patch_saved_query_sql(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.saved_query_reads.get_saved_query_sql", **kwargs)


def patch_node_type_update(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.saved_query_materialization.update_node_type", **kwargs)


def patch_deletion_dependents_check(**kwargs: Any) -> "_patch[MagicMock]":
    return patch(f"{_LOGIC}.saved_query_deletion.check_saved_query_deletable", **kwargs)


PATCH_HELPERS = (
    patch_temporal_client,
    patch_managed_warehouse_shadow_enabled,
    patch_access_check,
    patch_dag_reconcile,
    patch_dag_schedule_reconcile,
    patch_reconcile_capture,
    patch_frequency_target_apply,
    patch_column_describe_query,
    patch_column_describe_retry_sleep,
    patch_refresh_floor_flag,
    patch_saved_query_dag_sync,
    patch_saved_query_sql,
    patch_node_type_update,
    patch_deletion_dependents_check,
)

compile_hogql_for_ducklake = _compile_hogql_for_ducklake


def check_unique_key(batch: pa.RecordBatch, unique_key: tuple[str, ...]) -> None:
    """Raise when two rows of `batch` share a unique key, as a materialization does before it writes."""
    tracker = incremental_write.UniqueKeyTracker(unique_key)
    try:
        tracker.check(batch)
    finally:
        tracker.close()


def upsert_batch(
    table_uri: str,
    storage_options: dict[str, str],
    batch: pa.RecordBatch,
    unique_key: tuple[str, ...],
    *,
    commit_metadata: Optional[dict[str, str]] = None,
) -> None:
    """Insert-or-replace `batch` in the Delta table, keyed on `unique_key`."""
    incremental_write.upsert_batch(table_uri, storage_options, batch, unique_key, commit_metadata=commit_metadata)
