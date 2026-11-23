"""What a materialize attempt cost the worker, recorded on the job so a run can be priced.

ClickHouse reports what a query read, and the daily usage job copies that onto the job row. The
numbers here are the ones only the worker sees: the bytes it pulled over the network, the files it
put in object storage, and how long it held an activity slot.
"""

import json
import asyncio
from collections.abc import Collection, Mapping
from typing import Any, cast

from django.db.models import F, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Coalesce
from django.utils import timezone

import pyarrow as pa
import deltalake

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import DataModelingJob


def _read_live_file_sizes(delta_table: deltalake.DeltaTable) -> dict[str, int] | None:
    try:
        # delta-rs returns an arro3 table. pyarrow reads it through the Arrow PyCapsule interface,
        # which its type stubs do not declare.
        actions = pa.table(cast(Any, delta_table.get_add_actions(flatten=True)))
        paths = cast(list[str], actions.column("path").to_pylist())
        sizes = cast(list[int], actions.column("size_bytes").to_pylist())
        return dict(zip(paths, sizes))
    except Exception as error:
        capture_exception(error)
        return None


async def live_file_sizes(delta_table: deltalake.DeltaTable) -> dict[str, int] | None:
    """Size in bytes of each live data file, keyed by its path in the table, read from the Delta log.

    None when the log could not be read this way. The run has already committed its rows by the
    time this is called, so a failure here must not fail the run.
    """
    # Off the event loop because the cost grows with the file count and heartbeats share the loop.
    return await asyncio.to_thread(_read_live_file_sizes, delta_table)


@frozen(frozen=False)
class RunUsage:
    """Accumulates over one activity attempt. `record_run_usage` adds it to the job's totals."""

    result_bytes_received: int = 0
    delta_files_written: int = 0
    delta_bytes_written: int = 0
    # None until the attempt reaches the end of its write, so a failed attempt keeps the last value.
    delta_table_files: int | None = None
    delta_table_bytes: int | None = None

    def add_received(self, size: int) -> None:
        self.result_bytes_received += size

    def add_written(self, sizes: Mapping[str, int] | None, *, already_there: Collection[str] | None = ()) -> None:
        """Count the files in ``sizes`` that the attempt added, which is all but ``already_there``.

        A file that one batch added and a later batch of the same attempt replaced is in neither
        listing, so an incremental run with several batches is undercounted by those files.
        """
        if sizes is None or already_there is None:
            return
        added = [size for path, size in sizes.items() if path not in already_there]
        self.delta_files_written += len(added)
        self.delta_bytes_written += sum(added)

    def add_compaction(self, metrics: Mapping[str, Any]) -> None:
        try:
            # delta-rs returns the per-file summaries as JSON text inside the metrics mapping.
            files_added = metrics["filesAdded"]
            summary = json.loads(files_added) if isinstance(files_added, str) else files_added
            files, size = int(metrics["numFilesAdded"]), int(summary["totalSize"])
        except Exception as error:
            capture_exception(error)
            return
        self.delta_files_written += files
        self.delta_bytes_written += size

    def set_table(self, sizes: Mapping[str, int] | None) -> None:
        if sizes is None:
            return
        self.delta_table_files = len(sizes)
        self.delta_table_bytes = sum(sizes.values())


def _added_to(field: str, amount: int | float) -> CombinedExpression:
    return Coalesce(F(field), Value(0)) + Value(amount)


@database_sync_to_async_pool
def record_run_usage(*, team_id: int, job_id: str, usage: RunUsage, activity_seconds: float) -> None:
    """Add one attempt's usage to the job, so a retried run carries the cost of every attempt.

    Written as increments in the database because the activity saves the whole job row while it
    runs, from an instance that was read before the attempt started.
    """
    updates: dict[str, Any] = {
        "result_bytes_received": _added_to("result_bytes_received", usage.result_bytes_received),
        "delta_files_written": _added_to("delta_files_written", usage.delta_files_written),
        "delta_bytes_written": _added_to("delta_bytes_written", usage.delta_bytes_written),
        "activity_seconds": _added_to("activity_seconds", activity_seconds),
        # `update` skips auto_now, and the warehouse mirror of this table syncs rows by updated_at.
        "updated_at": timezone.now(),
    }
    if usage.delta_table_files is not None and usage.delta_table_bytes is not None:
        updates["delta_table_files"] = usage.delta_table_files
        updates["delta_table_bytes"] = usage.delta_table_bytes
    DataModelingJob.objects.filter(id=job_id, team_id=team_id).update(**updates)
