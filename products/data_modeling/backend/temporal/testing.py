"""Entry points into the incremental write for tests in other products."""

from typing import Optional

import pyarrow as pa

from products.data_modeling.backend.temporal.activities import incremental_write


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
