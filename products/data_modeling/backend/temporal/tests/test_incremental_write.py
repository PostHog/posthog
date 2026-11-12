"""UniqueKeyTracker in isolation: pure pyarrow, no database, no delta table.

The activity-level suite proves the tracker is wired into both write paths; these cover the
detection logic itself, where the cheap edge cases live (composite keys, the byte cap, a key
column missing from the output).
"""

import json
import struct
import tempfile
import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pyarrow as pa

from products.data_modeling.backend.temporal.activities.incremental_write import (
    MAX_UNIQUE_KEY_CHECK_BYTES,
    MAX_UNIQUE_KEY_SPILL_BYTES,
    IncrementalWriteError,
    UniqueKeyTracker,
    _TrackerClosed,
    upsert_batch,
)

_MODULE = "products.data_modeling.backend.temporal.activities.incremental_write"

_spill_modes = pytest.mark.parametrize("max_bytes", [1, MAX_UNIQUE_KEY_CHECK_BYTES], ids=["disk", "memory"])


def _float_from_bits(hex_bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(hex_bits))[0]


def _batch(ids: Sequence[int | None], names: Sequence[str | None]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [pa.array(ids, type=pa.int64()), pa.array(names, type=pa.string())],
        names=["id", "name"],
    )


@pytest.mark.parametrize(
    "batches,match",
    [
        pytest.param([([1, 1], ["a", "b"])], "appears 2 times", id="duplicate_within_a_batch"),
        pytest.param(
            [([1], ["a"]), ([2], ["b"]), ([1], ["c"])],
            "appears 2 times",
            id="duplicate_across_batches",
        ),
        pytest.param(
            [([1], ["a"]), ([1, 1, 2], ["b", "c", "d"])],
            "appears 3 times",
            id="seen_key_repeated_within_a_later_batch",
        ),
        pytest.param(
            [([1], ["a"]), ([1] * 5, ["b"] * 5)],
            "appears 6 times",
            id="seen_key_five_times_in_a_later_batch",
        ),
        pytest.param(
            [([9], ["a"]), ([9] + [5] * 5, ["b"] * 6)],
            "appears 5 times",
            id="within_batch_count_outweighs_a_seen_key",
        ),
        pytest.param(
            [([1, 2], ["a", "b"]), ([1, 2, 2, 2], ["c", "d", "e", "f"])],
            "appears 4 times",
            id="most_repeated_key_was_also_seen",
        ),
        pytest.param([([1, None], ["a", "b"])], "is null", id="null_key"),
    ],
)
@_spill_modes
def test_single_column_violations_are_detected(batches: list[tuple], match: str, max_bytes: int) -> None:
    tracker = UniqueKeyTracker(("id",), max_bytes=max_bytes)

    with pytest.raises(IncrementalWriteError, match=match):
        for ids, names in batches:
            tracker.check(_batch(ids, names))


def test_a_duplicate_split_across_slices_of_one_batch_is_detected() -> None:
    tracker = UniqueKeyTracker(("id",))

    with patch("products.data_modeling.backend.temporal.activities.incremental_write.UNIQUE_KEY_CHECK_SLICE_ROWS", 2):
        with pytest.raises(IncrementalWriteError, match="appears 2 times"):
            tracker.check(_batch([1, 2, 3, 1], ["a", "b", "c", "d"]))


def test_distinct_keys_across_batches_pass() -> None:
    tracker = UniqueKeyTracker(("id",))

    tracker.check(_batch([1, 2], ["a", "b"]))
    tracker.check(_batch([3, 4], ["c", "d"]))


@_spill_modes
def test_composite_key_is_checked_as_a_tuple(max_bytes: int) -> None:
    tracker = UniqueKeyTracker(("id", "name"), max_bytes=max_bytes)

    tracker.check(_batch([1, 1], ["a", "b"]))
    tracker.check(_batch([2, 2], ["a", "b"]))

    with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
        tracker.check(_batch([1], ["a"]))


@pytest.mark.parametrize(
    "value,other,same",
    [
        (-0.0, 0.0, False),
        (float("nan"), float("nan"), True),
        (_float_from_bits("7ff8000000000000"), _float_from_bits("7ff8000000000001"), False),
    ],
)
@_spill_modes
def test_float_keys_compare_alike_in_memory_and_on_disk(value: float, other: float, same: bool, max_bytes: int) -> None:
    tracker = UniqueKeyTracker(("key",), max_bytes=max_bytes)
    tracker.check(pa.record_batch([[value]], names=["key"]))
    with pytest.raises(IncrementalWriteError, match="appears 2 times") if same else contextlib.nullcontext():
        tracker.check(pa.record_batch([[other]], names=["key"]))
    tracker.close()


def test_a_missing_key_column_names_the_column() -> None:
    tracker = UniqueKeyTracker(("missing",))

    with pytest.raises(IncrementalWriteError, match="missing"):
        tracker.check(_batch([1], ["a"]))


def test_spilling_preserves_keys_from_earlier_batches() -> None:
    tracker = UniqueKeyTracker(("id",), max_bytes=8)

    tracker.check(_batch([1], ["a"]))
    tracker.check(_batch([2, 3, 4], ["b", "c", "d"]))
    with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
        tracker.check(_batch([1], ["a"]))
    tracker.close()


@pytest.mark.parametrize(
    "spill_bytes,free_reserve",
    [pytest.param(1, 0, id="index_budget"), pytest.param(MAX_UNIQUE_KEY_SPILL_BYTES, 1 << 62, id="free_disk")],
)
def test_the_spilled_index_fails_loudly_past_its_disk_budget(spill_bytes: int, free_reserve: int) -> None:
    tracker = UniqueKeyTracker(("id",), max_bytes=1)
    with (
        patch(f"{_MODULE}.MAX_UNIQUE_KEY_SPILL_BYTES", spill_bytes),
        patch(f"{_MODULE}.MIN_FREE_SPILL_DISK_BYTES", free_reserve),
        pytest.raises(IncrementalWriteError, match="too many unique keys to verify"),
    ):
        tracker.check(_batch([1, 2], ["a", "b"]))
    tracker.close()


def test_closing_removes_the_spilled_index(tmp_path: Path) -> None:
    with patch.object(tempfile, "tempdir", str(tmp_path)):
        tracker = UniqueKeyTracker(("id",), max_bytes=1)
        tracker.check(_batch([1], ["a"]))
    assert list(tmp_path.iterdir())

    tracker.close()

    assert not list(tmp_path.iterdir())


def test_closing_during_a_check_stops_it_and_removes_the_index(tmp_path: Path) -> None:
    with patch.object(tempfile, "tempdir", str(tmp_path)):
        tracker = UniqueKeyTracker(("id",), max_bytes=1)
        tracker.check(_batch([0], ["a"]))
    dumps = json.dumps

    def close_mid_insert(*args: Any, **kwargs: Any) -> str:
        tracker.close()
        return dumps(*args, **kwargs)

    ids = list(range(1, 20_000))
    with patch(f"{_MODULE}.json.dumps", side_effect=close_mid_insert), pytest.raises(_TrackerClosed):
        tracker.check(_batch(ids, ["x"] * len(ids)))

    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "row_group_cap,expected",
    [
        pytest.param(16 * 1024 * 1024, 16 * 1024 * 1024, id="cap_on"),
        pytest.param(0, None, id="zero_is_off"),
        pytest.param(-1, None, id="negative_is_off"),
    ],
)
def test_upsert_batch_passes_the_row_group_cap(row_group_cap: int, expected: int | None) -> None:
    fake_table = MagicMock()
    fake_deltalite = MagicMock()
    fake_deltalite.DeltaLiteTable.open.return_value = fake_table

    with (
        patch.dict("sys.modules", {"deltalite": fake_deltalite}),
        override_settings(DATA_WAREHOUSE_DELTALITE_MAX_ROW_GROUP_BYTES=row_group_cap),
    ):
        upsert_batch("s3://b/t", {}, _batch([1], ["a"]), ("id",), commit_metadata={"run_uuid": "abc"})

    fake_table.upsert.assert_called_once()
    kwargs = fake_table.upsert.call_args.kwargs
    assert kwargs["max_row_group_bytes"] == expected
    assert kwargs["commit_metadata"] == {"run_uuid": "abc"}
