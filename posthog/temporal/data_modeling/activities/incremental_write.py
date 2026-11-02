"""Upsert a batch of materialized rows into an existing Delta table, via deltalite.

deltalite rather than delta-rs's MERGE because it commits once per batch instead of once per
partition, keeps memory bounded, re-plans internally on a commit conflict, and — the reason that
matters most here — has no DataFusion in its dependency tree. delta-rs's MERGE routes through
DataFusion, which lowercases identifiers and then cannot resolve them again; data modeling is this
codebase's main producer of camelCase columns, so that path is a live hazard for us specifically.

deltalite's contract differs from MERGE's in four ways that each need handling rather than trust:

1. A NULL in a key column never matches, so the row is inserted instead of updated and the table
   gains a duplicate on every run, silently, forever.
2. Duplicate keys within one batch are a hard error that aborts the whole upsert.
3. There is no schema evolution. An extra source column errors; a *missing* one is null-padded,
   which overwrites the stored value with NULL.
4. It cannot create a table, only open one.

The first three are checked here, before the write, so each surfaces as a message naming the
column rather than as a Rust error or as quiet drift. The fourth is why the full-refresh path
stays on delta-rs.
"""

import json
import sqlite3
import weakref
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from django.conf import settings

import pyarrow as pa
import pyarrow.compute as pc

# Exact duplicate detection has to remember every distinct key a run has produced. Past this budget
# the keys move to a local SQLite index, so a huge materialization cannot OOM the worker. Peak memory
# of the in-memory check is about this state plus one slice, and a worker runs many activities at
# once, so the budget has to stay a small share of a pod.
MAX_UNIQUE_KEY_CHECK_BYTES = 1024 * 1024 * 1024

# A materialization batch is about 100 MB, so a narrow key-only table sends ~12M rows at once, and the
# group-by hash table for that many rows dwarfs the stored keys. Checking in slices keeps that bounded.
UNIQUE_KEY_CHECK_SLICE_ROWS = 1_000_000


class IncrementalWriteError(Exception):
    """A batch cannot be safely upserted. Carries a message meant for the run's error field."""


class SchemaDriftError(IncrementalWriteError):
    """The query's output no longer matches the stored table.

    Separate from its parent because the caller reacts differently: it clears the watermark so the
    next attempt rebuilds the table at the new schema, instead of null-padding rows into the old one.
    """


class TableUnreadableError(IncrementalWriteError):
    """deltalite found no usable log for a table that opened earlier in the same run.

    The cause can be a storage listing glitch or a concurrent rewrite. An upsert cannot repair the
    table in place, so the caller clears the watermark and the retry rebuilds it.
    """


def assert_schema_matches(batch: pa.RecordBatch, target: pa.Schema) -> None:
    """Refuse to upsert unless the batch's columns and types match the table's exactly.

    deltalite null-pads a column the batch is missing, which would overwrite stored values with
    NULL, and errors on a column the table lacks. Neither is recoverable in place, so any drift
    routes to a full refresh instead.
    """
    batch_names = set(batch.schema.names)
    target_names = set(target.names)

    missing = sorted(target_names - batch_names)
    extra = sorted(batch_names - target_names)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"no longer returns {', '.join(missing)}")
        if extra:
            parts.append(f"now returns {', '.join(extra)}")
        raise SchemaDriftError(f"The query's output changed: it {' and '.join(parts)}.")

    retyped = [
        f"{name} ({target.field(name).type} to {batch.schema.field(name).type})"
        for name in target.names
        if not batch.schema.field(name).type.equals(target.field(name).type)
    ]
    if retyped:
        raise SchemaDriftError(f"The query's column types changed: {', '.join(retyped)}.")


def assert_no_null_keys(batch: pa.RecordBatch, unique_key: tuple[str, ...]) -> None:
    """A null key can never match an existing row, so it would insert a duplicate every run."""
    for column in unique_key:
        null_count = pc.sum(pc.cast(pc.is_null(batch.column(column)), pa.int64())).as_py() or 0
        if null_count:
            raise IncrementalWriteError(
                f'Unique key column "{column}" is null in {null_count} row(s). A null key would add '
                f"duplicate rows on every run. Wrap it in coalesce() to give it a fallback value."
            )


class UniqueKeyTracker:
    """Exact unique-key enforcement across every batch of one materialization.

    Duplicate keys mean the declared unique key does not identify a row, and a duplicate is not
    deduplicated silently the way the import pipeline does: there a source genuinely emits a key
    twice, whereas here a duplicate means the config is wrong and quietly keeping one row would
    hide it. A per-batch check cannot see a duplicate split across batches — deltalite would turn
    it into an update, silently — so the distinct keys seen so far are carried across ``check``
    calls. Only key columns are retained, and a local SQLite index takes over when they exceed the
    memory budget. SQLite keeps its index on disk, so initial builds need no row-count limit.

    In memory, each call groups only the new batch, then probes the stored keys with a hash join whose
    build side is that small grouped batch. The stored keys are kept as a list of per-batch chunks and
    are never merged into one buffer or inserted into a hash table again. Each call only looks them up
    in the batch's small table, which is much cheaper than regrouping everything seen so far.
    """

    def __init__(self, unique_key: tuple[str, ...], max_bytes: int = MAX_UNIQUE_KEY_CHECK_BYTES) -> None:
        self._columns = list(unique_key)
        self._max_bytes = max_bytes
        self._seen_chunks: list[pa.Table] = []
        self._seen_bytes = 0
        self._spill: sqlite3.Connection | None = None
        self._resources = ExitStack()
        # Checks run on executor threads, so cleanup cannot depend on which thread releases the tracker.
        self._cleanup = weakref.finalize(self, self._resources.close)

    def close(self) -> None:
        self._cleanup()

    def _check_disk(self, keys: pa.Table) -> None:
        assert self._spill is not None

        def rows() -> Iterator[tuple[str]]:
            for batch in keys.to_batches(max_chunksize=8192):
                columns = batch.to_pydict().values()
                for row in zip(*columns, strict=True):
                    # Arrow groups positive and negative zero together. JSON otherwise preserves
                    # scalar equality within each fixed Arrow column type, including NaN and dates.
                    normalized = [0.0 if isinstance(value, float) and value == 0 else value for value in row]
                    yield (json.dumps(normalized, default=str, ensure_ascii=False, separators=(",", ":")),)

        try:
            with self._spill:
                self._spill.executemany("INSERT INTO unique_keys (key) VALUES (?)", rows())
        except sqlite3.IntegrityError as error:
            raise IncrementalWriteError(
                f"The unique key ({', '.join(self._columns)}) does not identify a single row: "
                "a key appears more than once in this run's result. Add the columns that tell those rows apart."
            ) from error

    def _start_spill(self) -> None:
        directory = self._resources.enter_context(TemporaryDirectory(prefix="posthog-materialization-keys-"))
        # Each check is awaited before the next starts, but asyncio.to_thread may choose another thread.
        self._spill = sqlite3.connect(Path(directory) / "keys.sqlite3", check_same_thread=False)
        self._resources.callback(self._spill.close)
        # The index is discarded with the run, so journaling and fsync buy nothing.
        self._spill.execute("PRAGMA journal_mode=OFF")
        self._spill.execute("PRAGMA synchronous=OFF")
        self._spill.execute("CREATE TABLE unique_keys (key TEXT PRIMARY KEY) WITHOUT ROWID")
        for chunk in self._seen_chunks:
            self._check_disk(chunk)
        self._seen_chunks = []

    def check(self, batch: pa.RecordBatch) -> None:
        """Fail if ``batch`` has a missing, null, or duplicate key — including a key already seen
        in an earlier batch of this run. Meant to run before the batch is written, so a violating
        batch never lands."""
        missing = [column for column in self._columns if column not in batch.schema.names]
        if missing:
            raise IncrementalWriteError(
                f"Unique key column(s) {', '.join(missing)} are not in the query's output. "
                f"Update the incremental configuration to match the query's columns."
            )
        assert_no_null_keys(batch, tuple(self._columns))
        for offset in range(0, max(batch.num_rows, 1), UNIQUE_KEY_CHECK_SLICE_ROWS):
            self._check_slice(batch.slice(offset, UNIQUE_KEY_CHECK_SLICE_ROWS))

    def _check_slice(self, batch: pa.RecordBatch) -> None:
        keys = pa.Table.from_batches([batch]).select(self._columns)
        if self._spill is not None:
            self._check_disk(keys)
            return
        grouped = keys.group_by(self._columns).aggregate([([], "count_all")])
        worst = pc.max(grouped.column("count_all")).as_py() if grouped.num_rows != keys.num_rows else 1
        if self._seen_chunks:
            # Acero builds the hash table on the right input, so the grouped batch goes on the right
            # and the stored keys are only streamed through it. Every stored key is distinct, so a
            # key found there occurs once more than its count in this batch.
            already_seen = pa.concat_tables(self._seen_chunks).join(grouped, keys=self._columns, join_type="right semi")
            if already_seen.num_rows:
                worst = max(worst, pc.max(already_seen.column("count_all")).as_py() + 1)
        if worst > 1:
            raise IncrementalWriteError(
                f"The unique key ({', '.join(self._columns)}) does not identify a single row: one key "
                f"appears {worst} times in this run's result. Add the columns that tell those rows apart."
            )

        distinct = grouped.select(self._columns).combine_chunks()
        self._seen_chunks.append(distinct)
        self._seen_bytes += distinct.nbytes
        if self._seen_bytes > self._max_bytes:
            self._start_spill()


def max_of(batch: pa.RecordBatch, column: str, running: Any = None) -> Any:
    """Running max of the incremental key, which becomes the next run's lower bound."""
    value = pc.max(batch.column(column)).as_py()
    if value is None:
        return running
    if running is None:
        return value
    try:
        return max(running, value)
    except TypeError:
        # Mixed types across batches mean the key is not comparable, so no watermark can be
        # trusted. Keeping the earlier value makes the next run re-read, which is the safe way to
        # be wrong.
        return running


def upsert_batch(
    table_uri: str,
    storage_options: dict[str, str],
    batch: pa.RecordBatch,
    unique_key: tuple[str, ...],
    *,
    commit_metadata: Optional[dict[str, str]] = None,
) -> Any:
    """Insert-or-replace ``batch`` keyed on ``unique_key``. Returns deltalite's UpsertStats.

    Opened per call because deltalite re-reads the log on every upsert anyway, and a handle held
    across a long streaming read would only go stale.
    """
    import deltalite

    max_row_group_bytes = settings.DATA_WAREHOUSE_DELTALITE_MAX_ROW_GROUP_BYTES
    try:
        lite = deltalite.DeltaLiteTable.open(table_uri, storage_options)
    except deltalite.DeltaLiteTableNotFoundError as err:
        raise TableUnreadableError(
            "The stored table could not be read during an incremental update. It will be rebuilt on the next attempt."
        ) from err
    return lite.upsert(
        pa.Table.from_batches([batch]),
        list(unique_key),
        None,
        commit_metadata=commit_metadata,
        max_row_group_bytes=max_row_group_bytes if max_row_group_bytes > 0 else None,
    )


def table_exists(table_uri: str, storage_options: dict[str, str]) -> bool:
    import deltalite

    try:
        return bool(deltalite.DeltaLiteTable.is_deltatable(table_uri, storage_options))
    except Exception:
        # Treated as absent, which routes to a full refresh: correct, just more expensive.
        return False


def upsert_stats_fields(stats: Any) -> dict[str, int | float | str | bool]:
    """Flatten UpsertStats into scalar log fields.

    Enumerated rather than named one by one so fields added crate-side show up without a change
    here. Best-effort: a stats read must never fail a committed write.
    """
    fields: dict[str, int | float | str | bool] = {}
    for name in dir(stats):
        if name.startswith("_"):
            continue
        try:
            value = getattr(stats, name)
        except Exception:  # noqa: BLE001 - a flaky getter must not break logging a committed write
            continue
        if isinstance(value, bool | int | float | str):
            fields[name] = value
    return fields
