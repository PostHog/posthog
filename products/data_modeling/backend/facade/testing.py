"""
Entry points into the materialization activities for tests in other products.

Production callers use ``facade/api.py`` and ``facade/temporal.py``. These helpers exist so a test in another product
can drive the incremental write and the HogQL compile without reaching into ``backend/temporal/``.

Imports the activity modules, so it must only be imported off the ``django.setup()`` path.
"""

from typing import Optional

import pyarrow as pa

from products.data_modeling.backend.temporal.activities import incremental_write
from products.data_modeling.backend.temporal.activities.materialize_view_managed_warehouse import (
    _compile_hogql_for_ducklake,
)

__all__ = ["check_unique_key", "compile_hogql_for_ducklake", "upsert_batch"]

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
