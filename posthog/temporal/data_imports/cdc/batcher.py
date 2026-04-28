from __future__ import annotations

from collections import defaultdict

import pyarrow as pa

from posthog.temporal.data_imports.cdc.types import ChangeEvent

# CDC metadata column names — database-agnostic
CDC_OP_COLUMN = "_ph_cdc_op"
CDC_TIMESTAMP_COLUMN = "_ph_cdc_timestamp"
DELETED_COLUMN = "_ph_deleted"
DELETED_AT_COLUMN = "_ph_deleted_at"

# SCD Type 2 columns added to the _cdc history table
SCD2_VALID_FROM_COLUMN = "valid_from"
SCD2_VALID_TO_COLUMN = "valid_to"

# Columns that are CDC/SCD2 metadata — always filled from the event itself,
# never overwritten when enriching DELETE rows with last-known source data.
_CDC_METADATA_COLUMNS: frozenset[str] = frozenset(
    {
        CDC_OP_COLUMN,
        CDC_TIMESTAMP_COLUMN,
        DELETED_COLUMN,
        DELETED_AT_COLUMN,
        SCD2_VALID_FROM_COLUMN,
        SCD2_VALID_TO_COLUMN,
    }
)


# Micro-batch thresholds for CDC WAL processing.  Flushing periodically
# prevents unbounded memory growth when the WAL backlog is very large.
CDC_FLUSH_MAX_EVENTS = 5_000
CDC_FLUSH_MAX_BYTES = 128 * 1024 * 1024  # 128 MiB (estimated, pre-Arrow)


class ChangeEventBatcher:
    """Converts ChangeEvent objects into PyArrow tables grouped by table name.

    Each table contains source columns plus CDC metadata columns:
    - _ph_cdc_op: operation type (I/U/D)
    - _ph_cdc_timestamp: commit timestamp
    - _ph_deleted: soft-delete flag (True for D, False for I/U)
    - _ph_deleted_at: timestamp when deleted (null for I/U)

    Supports micro-batch flushing: check ``should_flush`` after each ``add()``
    to trigger periodic flushes and avoid OOMs on large WAL backlogs.
    """

    def __init__(
        self,
        max_events: int = CDC_FLUSH_MAX_EVENTS,
        max_bytes: int = CDC_FLUSH_MAX_BYTES,
    ) -> None:
        self._events: defaultdict[str, list[ChangeEvent]] = defaultdict(list)
        self._estimated_bytes: int = 0
        self._max_events = max_events
        self._max_bytes = max_bytes

    def add(self, event: ChangeEvent) -> None:
        self._events[event.table_name].append(event)
        self._estimated_bytes += self._estimate_event_bytes(event)

    @property
    def should_flush(self) -> bool:
        """Whether buffered events exceed the configured thresholds."""
        return self.event_count >= self._max_events or self._estimated_bytes >= self._max_bytes

    def flush(self) -> dict[str, pa.Table]:
        """Convert buffered events into PyArrow tables, one per table name.

        Returns empty dict if no events buffered.
        """
        result: dict[str, pa.Table] = {}

        for table_name, events in self._events.items():
            if not events:
                continue
            result[table_name] = _events_to_table(events)

        self._events.clear()
        self._estimated_bytes = 0
        return result

    @property
    def event_count(self) -> int:
        return sum(len(events) for events in self._events.values())

    @property
    def table_names(self) -> list[str]:
        return list(self._events.keys())

    @staticmethod
    def _estimate_event_bytes(event: ChangeEvent) -> int:
        """Rough memory estimate for a single change event (in bytes)."""
        size = 200  # base overhead: dataclass, strings, datetime, dict
        for key, val in event.columns.items():
            size += len(key) + 50  # key string + dict entry overhead
            if isinstance(val, (str, bytes)):
                size += len(val)
            elif val is not None:
                size += 8
        return size


def _safe_pa_array(values: list, target_type: pa.DataType) -> pa.Array:
    """Build a pa.Array, falling back to type inference if the explicit cast fails.

    Enrichment can produce mixed Python types in a single column — e.g. the
    incoming batch stores a decimal column as ``str`` while existing DeltaLake
    rows yield ``decimal.Decimal`` via ``.as_py()``. We try three strategies:

    1. Explicit type (``target_type``) — fastest, works when types match.
    2. PyArrow auto-inference — works when all values share a type.
    3. Coerce everything to ``str`` — last resort for mixed-type lists.
    """
    try:
        return pa.array(values, type=target_type)
    except (pa.ArrowTypeError, pa.ArrowInvalid):
        try:
            arr = pa.array(values)
            if arr.type == pa.null():
                return arr.cast(pa.string())
            return arr
        except (pa.ArrowTypeError, pa.ArrowInvalid):
            return pa.array([str(v) if v is not None else None for v in values], type=pa.string())


def enrich_delete_rows(
    table: pa.Table,
    pk_columns: list[str],
    existing_rows: pa.Table | None = None,
) -> pa.Table:
    """Fill data columns on DELETE rows from the last known state.

    PostgreSQL CDC DELETE events only carry identity (PK) columns. This function
    fills in the remaining data columns so that the deleted row retains its last
    visible values.

    Resolution order (highest priority first):
    1. The last preceding non-DELETE row with the same PK in this batch.
    2. The corresponding row in `existing_rows` (e.g. the current DeltaLake state
       passed in from the load processor for cross-batch enrichment).

    Note: This function materializes columns to Python lists via to_pylist().
    The processor pre-filters `existing_rows` to only the PKs present in DELETE
    events before calling this, so the materialization is bounded by the batch size.

    Metadata columns (op, timestamp, deleted flags, valid_from/to) are always
    kept from the DELETE event itself and are never overwritten.
    """
    if not pk_columns or table.num_rows == 0:
        return table

    present_pks = [col for col in pk_columns if col in table.column_names]
    if not present_pks:
        return table

    ops = table.column(CDC_OP_COLUMN).to_pylist()
    delete_indices = [i for i, op in enumerate(ops) if op == "D"]
    if not delete_indices:
        return table

    pk_set = set(present_pks)
    table_data_cols = [col for col in table.column_names if col not in _CDC_METADATA_COLUMNS and col not in pk_set]

    # Determine extra columns that exist in existing_rows but not in the current table.
    # A standalone DELETE event may only carry PK columns — we add the missing data
    # columns (all null for non-DELETE rows, then filled for DELETE rows below).
    extra_cols_from_existing: list[str] = []
    if existing_rows is not None and existing_rows.num_rows > 0:
        extra_cols_from_existing = [
            col
            for col in existing_rows.column_names
            if col not in _CDC_METADATA_COLUMNS and col not in pk_set and col not in table.column_names
        ]

    all_data_cols = table_data_cols + extra_cols_from_existing
    if not all_data_cols:
        return table

    pk_arrays = [table.column(col).to_pylist() for col in present_pks]

    # Build lookup: pk_tuple -> data from last non-DELETE row in this batch
    batch_lookup: dict[tuple, dict[str, object]] = {}
    for i, op in enumerate(ops):
        if op != "D":
            key = tuple(arr[i] for arr in pk_arrays)
            batch_lookup[key] = {col: table.column(col)[i].as_py() for col in table_data_cols}

    # Build lookup from existing DeltaLake rows (cross-batch fallback)
    existing_lookup: dict[tuple, dict[str, object]] = {}
    if existing_rows is not None and existing_rows.num_rows > 0:
        ex_present_pks = [col for col in present_pks if col in existing_rows.column_names]
        if len(ex_present_pks) == len(present_pks):
            ex_pk_arrays = [existing_rows.column(col).to_pylist() for col in present_pks]
            for i in range(existing_rows.num_rows):
                key = tuple(arr[i] for arr in ex_pk_arrays)
                # Last row for the same PK wins (in case of multiple existing rows)
                existing_lookup[key] = {
                    col: existing_rows.column(col)[i].as_py()
                    for col in all_data_cols
                    if col in existing_rows.column_names
                }

    # Start with all rows as Python lists; for extra_cols, initialise to null
    row_data: dict[str, list] = {col: table.column(col).to_pylist() for col in table_data_cols}
    for col in extra_cols_from_existing:
        row_data[col] = [None] * table.num_rows

    for i in delete_indices:
        key = tuple(arr[i] for arr in pk_arrays)
        source = batch_lookup.get(key) or existing_lookup.get(key)
        if source:
            for col in all_data_cols:
                # Only fill if the DELETE row's column is currently null
                if row_data[col][i] is None and source.get(col) is not None:
                    row_data[col][i] = source[col]

    # Rebuild table — replace/extend columns.  Extra columns are added after the
    # existing ones so the schema grows but doesn't change existing field positions.
    new_columns: dict[str, pa.Array | pa.ChunkedArray] = {}
    new_fields: list[pa.Field] = []
    for field in table.schema:
        col = field.name
        if col in row_data:
            col_type = field.type
            # If enrichment filled real values into a column that was originally all-null
            # (inferred as pa.null() by PyArrow), upgrade the type from existing_rows so
            # that pa.array() doesn't reject non-null values.
            if col_type == pa.null() and existing_rows is not None and col in existing_rows.column_names:
                col_type = existing_rows.schema.field(col).type
            arr = _safe_pa_array(row_data[col], col_type)
            new_columns[col] = arr
            new_fields.append(pa.field(col, arr.type))
        else:
            new_columns[col] = table.column(col)
            new_fields.append(field)

    result = pa.table(new_columns, schema=pa.schema(new_fields))

    for col in extra_cols_from_existing:
        ex_type = existing_rows.schema.field(col).type  # type: ignore[union-attr]
        arr = _safe_pa_array(row_data[col], ex_type)
        result = result.append_column(pa.field(col, arr.type), arr)

    return result


def deduplicate_table(pa_table: pa.Table, pk_columns: list[str]) -> pa.Table:
    """Keep only the last row per primary key in a CDC batch.

    Rows are assumed to be in WAL order (oldest first). For each unique PK tuple
    the last (most recent) row survives. If pk_columns is empty or none of the PK
    columns are present in the table, the original table is returned unchanged.
    """
    if not pk_columns or pa_table.num_rows == 0:
        return pa_table

    present_pks = [col for col in pk_columns if col in pa_table.column_names]
    if not present_pks:
        return pa_table

    pk_arrays = [pa_table.column(col).to_pylist() for col in present_pks]

    # Track the last row index seen for each PK tuple
    pk_to_last_idx: dict[tuple, int] = {}
    for i in range(pa_table.num_rows):
        key = tuple(arr[i] for arr in pk_arrays)
        pk_to_last_idx[key] = i

    # Preserve original row ordering
    indices = sorted(pk_to_last_idx.values())
    return pa_table.take(indices)


def build_scd2_table(pa_table: pa.Table, pk_columns: list[str]) -> pa.Table:
    """Add SCD Type 2 columns (valid_from, valid_to) to a raw CDC event table.

    valid_from  = _ph_cdc_timestamp (the commit timestamp of this event)
    valid_to    = _ph_cdc_timestamp of the next event for the same PK, or null
                  for the most recent event in the batch.

    The caller uses valid_to IS NULL to identify the current state of each row.
    DELETE events are included and can be the "current" row until a new event
    for the same PK arrives.

    A two-step merge + append in the load processor closes previous "current"
    rows (sets valid_to) when a new batch is written for the same PK.
    """
    ts_type = pa.timestamp("us", tz="UTC")

    if pa_table.num_rows == 0:
        return pa_table.append_column(
            pa.field(SCD2_VALID_FROM_COLUMN, ts_type), pa.array([], type=ts_type)
        ).append_column(pa.field(SCD2_VALID_TO_COLUMN, ts_type), pa.array([], type=ts_type))

    ts_col = pa_table.column(CDC_TIMESTAMP_COLUMN).to_pylist()

    present_pks = [col for col in pk_columns if col in pa_table.column_names]

    valid_to: list = [None] * pa_table.num_rows

    if present_pks:
        pk_arrays = [pa_table.column(col).to_pylist() for col in present_pks]

        # Collect row indices per PK in WAL order
        pk_to_row_indices: dict[tuple, list[int]] = {}
        for i in range(pa_table.num_rows):
            key = tuple(arr[i] for arr in pk_arrays)
            pk_to_row_indices.setdefault(key, []).append(i)

        # For each PK group, set valid_to[i] = valid_from[i+1] (the next event)
        for row_indices in pk_to_row_indices.values():
            for j, idx in enumerate(row_indices[:-1]):
                next_idx = row_indices[j + 1]
                valid_to[idx] = ts_col[next_idx]

    return pa_table.append_column(
        pa.field(SCD2_VALID_FROM_COLUMN, ts_type),
        pa_table.column(CDC_TIMESTAMP_COLUMN),
    ).append_column(
        pa.field(SCD2_VALID_TO_COLUMN, ts_type),
        pa.array(valid_to, type=ts_type),
    )


def _events_to_table(events: list[ChangeEvent]) -> pa.Table:
    """Convert a list of ChangeEvents (same table) to a PyArrow table with CDC metadata."""
    # Collect all column names across all events (order-preserving)
    all_columns: dict[str, None] = {}
    for event in events:
        for col_name in event.columns:
            all_columns[col_name] = None
    column_names = list(all_columns.keys())

    # Build column arrays
    source_data: dict[str, list] = {col: [] for col in column_names}
    cdc_ops: list[str] = []
    cdc_timestamps: list[int] = []  # microseconds since epoch
    deleted_flags: list[bool] = []
    deleted_at: list[int | None] = []

    for event in events:
        for col_name in column_names:
            source_data[col_name].append(event.columns.get(col_name))

        cdc_ops.append(event.operation)
        ts_us = int(event.timestamp.timestamp() * 1_000_000)
        cdc_timestamps.append(ts_us)
        is_delete = event.operation == "D"
        deleted_flags.append(is_delete)
        deleted_at.append(ts_us if is_delete else None)

    # Build PyArrow arrays for source columns.
    # If type inference fails (e.g. mixed int/str from a schema change mid-WAL),
    # fall back to storing the column as strings.
    # Also upgrade pa.null() → pa.string() since DeltaLake rejects the Null type
    # (happens when a DELETE-only batch has all-None values for non-PK columns).
    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []
    for col_name in column_names:
        try:
            arr = pa.array(source_data[col_name])
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            arr = pa.array([str(v) if v is not None else None for v in source_data[col_name]], type=pa.string())
        if arr.type == pa.null():
            arr = arr.cast(pa.string())
        arrays.append(arr)
        fields.append(pa.field(col_name, arr.type))

    # Add CDC metadata columns
    arrays.append(pa.array(cdc_ops, type=pa.string()))
    fields.append(pa.field(CDC_OP_COLUMN, pa.string()))

    arrays.append(pa.array(cdc_timestamps, type=pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(CDC_TIMESTAMP_COLUMN, pa.timestamp("us", tz="UTC")))

    arrays.append(pa.array(deleted_flags, type=pa.bool_()))
    fields.append(pa.field(DELETED_COLUMN, pa.bool_()))

    arrays.append(pa.array(deleted_at, type=pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(DELETED_AT_COLUMN, pa.timestamp("us", tz="UTC")))

    schema = pa.schema(fields)
    return pa.table(arrays, schema=schema)
