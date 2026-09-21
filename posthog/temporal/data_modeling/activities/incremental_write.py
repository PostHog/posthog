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

from typing import Any, Optional

import pyarrow as pa
import pyarrow.compute as pc

# Exact duplicate detection has to remember every distinct key a run has produced. The cap bounds
# that state so a huge materialization cannot OOM the worker; hitting it fails the run loudly
# rather than quietly skipping verification.
MAX_UNIQUE_KEY_CHECK_BYTES = 256 * 1024 * 1024


class IncrementalWriteError(Exception):
    """A batch cannot be safely upserted. Carries a message meant for the run's error field."""


class SchemaDriftError(IncrementalWriteError):
    """The query's output no longer matches the stored table.

    Separate from its parent because the caller reacts differently: it clears the watermark so the
    next attempt rebuilds the table at the new schema, instead of null-padding rows into the old one.
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
    calls. Only the key columns of the group_by output are retained, so memory grows with distinct
    keys, not rows, and the byte cap turns "too big to verify" into a loud failure.
    """

    def __init__(self, unique_key: tuple[str, ...], max_bytes: int = MAX_UNIQUE_KEY_CHECK_BYTES) -> None:
        self._columns = list(unique_key)
        self._max_bytes = max_bytes
        self._seen: pa.Table | None = None

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

        keys = pa.Table.from_batches([batch]).select(self._columns)
        combined = keys if self._seen is None else pa.concat_tables([self._seen, keys])
        grouped = combined.group_by(self._columns).aggregate([([], "count_all")])
        if grouped.num_rows != combined.num_rows:
            worst = pc.max(grouped.column("count_all")).as_py()
            raise IncrementalWriteError(
                f"The unique key ({', '.join(self._columns)}) does not identify a single row: one key "
                f"appears {worst} times in this run's result. Add the columns that tell those rows apart."
            )

        seen = grouped.select(self._columns)
        if seen.nbytes > self._max_bytes:
            raise IncrementalWriteError(
                f"This query returns too many unique keys to verify ({seen.num_rows} so far). "
                f"Reduce the rows the query returns, or turn off incremental materialization for "
                f"this view to fall back to a full refresh."
            )
        self._seen = seen


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

    lite = deltalite.DeltaLiteTable.open(table_uri, storage_options)
    return lite.upsert(
        pa.Table.from_batches([batch]),
        list(unique_key),
        None,
        commit_metadata=commit_metadata,
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
