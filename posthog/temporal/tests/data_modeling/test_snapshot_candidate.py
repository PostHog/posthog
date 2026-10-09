from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import pyarrow as pa
import deltalake

from posthog.temporal.data_modeling.activities.materialize_view import prepare_batch_for_delta
from posthog.temporal.data_modeling.activities.snapshot import (
    SnapshotCandidateBuilder,
    cleanup_snapshot_generations,
    snapshot_generation_uri,
)

from products.data_modeling.backend.facade.api import SnapshotConfig, SnapshotValidationError


def test_snapshot_candidate_streams_changes_into_a_new_generation(tmp_path: Path) -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    observed_at = datetime(2026, 1, 2, tzinfo=UTC)
    parent_uri = str(tmp_path / "parent")
    candidate_uri = str(tmp_path / "candidate")
    history = pa.table(
        {
            "id": [1, 2, 3, 4],
            "name": ["stable", "old", "gone", "historical"],
            "valid_from": pa.array([first, first, first, first - timedelta(days=1)], type=pa.timestamp("us", tz="UTC")),
            "valid_to": pa.array([None, None, None, first], type=pa.timestamp("us", tz="UTC")),
            "_ph_snapshot_version_id": ["v1", "v2", "v3", "v4"],
        }
    )
    deltalake.write_deltalake(parent_uri, history)
    observation = pa.table({"id": [1, 2, 5], "name": ["stable", "new", "added"]})

    with SnapshotCandidateBuilder(tmp_path / "observation.sqlite", SnapshotConfig(unique_key=("id",))) as builder:
        builder.add_batch(observation.slice(0, 2).to_batches()[0])
        builder.add_batch(observation.slice(2).to_batches()[0])
        result = builder.write(
            parent_uri=parent_uri,
            generation_uri=candidate_uri,
            storage_options={},
            observed_at=observed_at,
            generation="model",
            run_id="run",
        )

    rows = deltalake.DeltaTable(candidate_uri).to_pyarrow_table().to_pylist()
    assert sorted((row["id"], row["name"], row["valid_to"]) for row in rows) == [
        (1, "stable", None),
        (2, "new", None),
        (2, "old", observed_at),
        (3, "gone", observed_at),
        (4, "historical", first),
        (5, "added", None),
    ]
    assert result.row_count == 6
    assert result.stats.inserted == 1
    assert result.stats.changed == 1
    assert result.stats.removed == 1
    assert result.stats.unchanged == 1
    assert result.stats.rows_scanned == 3


def test_snapshot_candidate_rejects_a_duplicate_key_across_batches(tmp_path: Path) -> None:
    config = SnapshotConfig(unique_key=("id",))
    with SnapshotCandidateBuilder(tmp_path / "observation.sqlite", config) as builder:
        builder.add_batch(pa.record_batch({"id": [1], "name": ["first"]}))
        with pytest.raises(SnapshotValidationError, match="unique key is not unique"):
            builder.add_batch(pa.record_batch({"id": [1], "name": ["second"]}))


class _FakeS3:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries
        self.deleted: list[str] = []

    def ls(self, _path: str, detail: bool = False) -> list[dict[str, Any]]:
        assert detail is True
        return self.entries

    def delete(self, path: str, recursive: bool = False) -> None:
        assert recursive is True
        self.deleted.append(path)


def test_snapshot_generation_cleanup_deletes_only_expired_unprotected_generations() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    table_uri = "s3://bucket/table"
    old = snapshot_generation_uri(table_uri, now - timedelta(hours=2), "old")
    current = snapshot_generation_uri(table_uri, now - timedelta(hours=3), "current")
    active = snapshot_generation_uri(table_uri, now - timedelta(hours=3), "active")
    recent = snapshot_generation_uri(table_uri, now - timedelta(minutes=30), "recent")
    candidate = snapshot_generation_uri(table_uri, now, "candidate")
    uris = [old, current, active, recent, candidate, f"{table_uri}/snapshot-generations/legacy"]
    s3 = _FakeS3([{"Key": uri.split("://", 1)[-1], "type": "directory"} for uri in uris])

    deleted = cleanup_snapshot_generations(
        s3,
        table_uri=table_uri,
        current_generation_uri=current,
        candidate_generation_uri=candidate,
        active_run_ids={"active"},
        now=now,
    )

    assert deleted == [old]
    assert s3.deleted == [old]


def test_snapshot_second_run_accepts_history_written_from_unsigned_clickhouse_columns(tmp_path: Path) -> None:
    # ClickHouse returns small literals as UInt8; Delta stores them signed, so the next run must compare signed types.
    config = SnapshotConfig(unique_key=("id",))
    ch_types = [("id", "UInt8"), ("name", "String")]
    batch = pa.record_batch({"id": pa.array([1, 2], type=pa.uint8()), "name": ["a", "b"]})
    first_uri = str(tmp_path / "first")

    with SnapshotCandidateBuilder(tmp_path / "first.sqlite", config) as builder:
        builder.add_batch(prepare_batch_for_delta(batch, ch_types))
        builder.write(
            parent_uri=None,
            generation_uri=first_uri,
            storage_options={},
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            generation="model",
            run_id="first",
        )

    with SnapshotCandidateBuilder(tmp_path / "second.sqlite", config) as builder:
        builder.add_batch(prepare_batch_for_delta(batch, ch_types))
        result = builder.write(
            parent_uri=first_uri,
            generation_uri=str(tmp_path / "second"),
            storage_options={},
            observed_at=datetime(2026, 1, 2, tzinfo=UTC),
            generation="model",
            run_id="second",
        )

    assert result.stats.unchanged == 2
