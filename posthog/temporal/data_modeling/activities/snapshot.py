import re
import json
import pickle
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pyarrow as pa
import deltalake

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import (
    SNAPSHOT_RESERVED_COLUMNS,
    SnapshotConfig,
    SnapshotStats,
    SnapshotValidationError,
    snapshot_row_key,
    snapshot_values_equal,
    snapshot_version_id,
)

SNAPSHOT_GENERATION_RETENTION = timedelta(hours=1)
_OUTPUT_BATCH_SIZE = 10_000
_GENERATION_NAME = re.compile(r"^(?P<created_at>\d+)_(?P<run_id>.+)$")


class _S3FileSystem(Protocol):
    def ls(self, path: str, detail: bool = False) -> Any: ...

    def delete(self, path: str, recursive: bool = False) -> Any: ...


@frozen
class SnapshotBuildResult:
    row_count: int
    file_uris: list[str]
    stats: SnapshotStats


def snapshot_generation_uri(table_uri: str, created_at: datetime, run_id: str) -> str:
    return f"{table_uri.rstrip('/')}/snapshot-generations/{int(created_at.timestamp())}_{run_id}"


def cleanup_snapshot_generations(
    s3: _S3FileSystem,
    *,
    table_uri: str,
    current_generation_uri: str | None,
    candidate_generation_uri: str,
    active_run_ids: set[str],
    now: datetime,
) -> list[str]:
    root_uri = f"{table_uri.rstrip('/')}/snapshot-generations"
    try:
        listed = s3.ls(root_uri, detail=True)
    except FileNotFoundError:
        return []

    entries = listed.values() if isinstance(listed, dict) else listed
    protected = {
        uri.split("://", 1)[-1].rstrip("/")
        for uri in (current_generation_uri, candidate_generation_uri)
        if uri is not None
    }
    cutoff = int((now - SNAPSHOT_GENERATION_RETENTION).timestamp())
    deleted: list[str] = []
    for entry in entries:
        if entry.get("type") != "directory":
            continue
        key = str(entry["Key"]).split("://", 1)[-1].rstrip("/")
        if key in protected:
            continue
        match = _GENERATION_NAME.fullmatch(key.rsplit("/", 1)[-1])
        if match is None or match.group("run_id") in active_run_ids or int(match.group("created_at")) > cutoff:
            continue
        uri = f"s3://{key}"
        try:
            s3.delete(uri, recursive=True)
        except FileNotFoundError:
            pass
        deleted.append(uri)
    return deleted


class SnapshotCandidateBuilder:
    def __init__(self, path: Path, config: SnapshotConfig) -> None:
        self._config = config
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode = OFF")
        self._connection.execute("PRAGMA synchronous = OFF")
        self._connection.execute("PRAGMA temp_store = FILE")
        self._connection.execute(
            "CREATE TABLE observations (key TEXT PRIMARY KEY, payload BLOB NOT NULL, handled INTEGER NOT NULL DEFAULT 0)"
        )
        self._connection.execute("CREATE TABLE open_history_keys (key TEXT PRIMARY KEY)")
        self._schema: pa.Schema | None = None
        self._rows_scanned = 0
        self._row_count = 0
        self._inserted = 0
        self._changed = 0
        self._removed = 0
        self._unchanged = 0

    def __enter__(self) -> "SnapshotCandidateBuilder":
        return self

    def __exit__(self, *_args: object) -> None:
        self._connection.close()

    @staticmethod
    def _serialized_key(key: tuple[Any, ...]) -> str:
        return json.dumps(key, separators=(",", ":"))

    def add_batch(self, batch: pa.RecordBatch) -> None:
        if SNAPSHOT_RESERVED_COLUMNS.intersection(batch.schema.names):
            raise SnapshotValidationError("Query output uses a reserved snapshot column.")
        missing_keys = set(self._config.unique_key) - set(batch.schema.names)
        if missing_keys:
            raise SnapshotValidationError(f"Snapshot key column is missing: {sorted(missing_keys)[0]}")
        if self._schema is None:
            self._schema = batch.schema
        elif not self._schema.equals(batch.schema, check_metadata=False):
            raise SnapshotValidationError("Snapshot query output schema changed within one observation.")

        observations = []
        for row in batch.to_pylist():
            key = self._serialized_key(snapshot_row_key(row, self._config))
            observations.append((key, pickle.dumps(row, protocol=pickle.HIGHEST_PROTOCOL)))
        try:
            self._connection.executemany("INSERT INTO observations (key, payload) VALUES (?, ?)", observations)
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise SnapshotValidationError("Snapshot unique key is not unique across the complete result.") from error
        self._rows_scanned += batch.num_rows

    def _candidate_schema(self) -> pa.Schema:
        if self._schema is None:
            raise SnapshotValidationError("Snapshot query returned no schema.")
        return (
            self._schema.append(pa.field("valid_from", pa.timestamp("us", tz="UTC")))
            .append(pa.field("valid_to", pa.timestamp("us", tz="UTC")))
            .append(pa.field("_ph_snapshot_version_id", pa.string()))
        )

    def _validate_parent_schema(self, schema: pa.Schema) -> None:
        assert self._schema is not None
        parent_fields = {field.name: field.type for field in schema if field.name not in SNAPSHOT_RESERVED_COLUMNS}
        observed_fields = {field.name: field.type for field in self._schema}
        if parent_fields != observed_fields:
            raise SnapshotValidationError("Snapshot query output schema changed after initialization.")

    def _new_version(
        self,
        row: dict[str, Any],
        key: tuple[Any, ...],
        *,
        observed_at: datetime,
        generation: str,
        run_id: str,
    ) -> dict[str, Any]:
        version = dict(row)
        version["valid_from"] = observed_at
        version["valid_to"] = None
        version["_ph_snapshot_version_id"] = snapshot_version_id(generation, key, run_id)
        return version

    def _candidate_rows(
        self,
        *,
        parent_reader: pa.RecordBatchReader | None,
        observed_at: datetime,
        generation: str,
        run_id: str,
    ) -> Iterator[dict[str, Any]]:
        latest_observation: datetime | None = None
        if parent_reader is not None:
            for batch in parent_reader:
                for row in batch.to_pylist():
                    valid_from = row.get("valid_from")
                    if isinstance(valid_from, datetime):
                        latest_observation = max(latest_observation, valid_from) if latest_observation else valid_from
                    if row.get("valid_to") is not None:
                        yield row
                        continue

                    key_tuple = snapshot_row_key(row, self._config)
                    key = self._serialized_key(key_tuple)
                    try:
                        self._connection.execute("INSERT INTO open_history_keys (key) VALUES (?)", (key,))
                    except sqlite3.IntegrityError as error:
                        raise SnapshotValidationError(
                            "History contains more than one open version for a key."
                        ) from error
                    observed = self._connection.execute(
                        "SELECT payload FROM observations WHERE key = ?", (key,)
                    ).fetchone()
                    if observed is None:
                        closed = dict(row)
                        closed["valid_to"] = observed_at
                        self._removed += 1
                        yield closed
                        continue

                    observed_row = pickle.loads(observed[0])
                    self._connection.execute("UPDATE observations SET handled = 1 WHERE key = ?", (key,))
                    if snapshot_values_equal(row, observed_row, self._config):
                        self._unchanged += 1
                        yield row
                        continue

                    closed = dict(row)
                    closed["valid_to"] = observed_at
                    self._changed += 1
                    yield closed
                    yield self._new_version(
                        observed_row,
                        key_tuple,
                        observed_at=observed_at,
                        generation=generation,
                        run_id=run_id,
                    )
                self._connection.commit()

        if latest_observation is not None and observed_at <= latest_observation:
            raise SnapshotValidationError("Snapshot observation time must be later than the previous observation.")

        cursor = self._connection.execute("SELECT key, payload FROM observations WHERE handled = 0 ORDER BY key")
        while rows := cursor.fetchmany(_OUTPUT_BATCH_SIZE):
            for key, payload in rows:
                observed_row = pickle.loads(payload)
                key_tuple = tuple(json.loads(key))
                self._inserted += 1
                yield self._new_version(
                    observed_row,
                    key_tuple,
                    observed_at=observed_at,
                    generation=generation,
                    run_id=run_id,
                )

    def _candidate_batches(self, rows: Iterator[dict[str, Any]], schema: pa.Schema) -> Iterator[pa.RecordBatch]:
        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(row)
            self._row_count += 1
            if len(output) == _OUTPUT_BATCH_SIZE:
                yield pa.RecordBatch.from_pylist(output, schema=schema)
                output = []
        if output:
            yield pa.RecordBatch.from_pylist(output, schema=schema)

    def write(
        self,
        *,
        parent_uri: str | None,
        generation_uri: str,
        storage_options: dict[str, str],
        observed_at: datetime,
        generation: str,
        run_id: str,
    ) -> SnapshotBuildResult:
        schema = self._candidate_schema()
        parent_reader: pa.RecordBatchReader | None = None
        if parent_uri is not None:
            parent = deltalake.DeltaTable(parent_uri, storage_options=storage_options)
            dataset = parent.to_pyarrow_dataset()
            self._validate_parent_schema(dataset.schema)
            parent_reader = dataset.scanner(batch_size=_OUTPUT_BATCH_SIZE).to_reader()
        rows = self._candidate_rows(
            parent_reader=parent_reader,
            observed_at=observed_at,
            generation=generation,
            run_id=run_id,
        )
        reader = pa.RecordBatchReader.from_batches(schema, self._candidate_batches(rows, schema))
        deltalake.write_deltalake(
            table_or_uri=generation_uri,
            data=reader,
            mode="overwrite",
            schema_mode="overwrite",
            storage_options=storage_options,
        )
        delta_table = deltalake.DeltaTable(generation_uri, storage_options=storage_options)
        return SnapshotBuildResult(
            row_count=self._row_count,
            file_uris=delta_table.file_uris(),
            stats=SnapshotStats(
                inserted=self._inserted,
                changed=self._changed,
                removed=self._removed,
                unchanged=self._unchanged,
                rows_scanned=self._rows_scanned,
            ),
        )
