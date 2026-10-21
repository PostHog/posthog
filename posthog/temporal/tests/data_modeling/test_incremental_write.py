"""UniqueKeyTracker in isolation: pure pyarrow, no database, no delta table.

The activity-level suite proves the tracker is wired into both write paths; these cover the
detection logic itself, where the cheap edge cases live (composite keys, the byte cap, a key
column missing from the output).
"""

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pyarrow as pa

from posthog.temporal.data_modeling.activities.incremental_write import (
    MAX_UNIQUE_KEY_CHECK_BYTES,
    IncrementalWriteError,
    UniqueKeyTracker,
    upsert_batch,
)

_spill_modes = pytest.mark.parametrize("max_bytes", [1, MAX_UNIQUE_KEY_CHECK_BYTES], ids=["disk", "memory"])


def _batch(ids: list[int | None], names: list[str | None]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [pa.array(ids, type=pa.int64()), pa.array(names, type=pa.string())],
        names=["id", "name"],
    )


@pytest.mark.parametrize(
    "batches,match",
    [
        pytest.param([([1, 1], ["a", "b"])], "does not identify a single row", id="duplicate_within_a_batch"),
        pytest.param(
            [([1], ["a"]), ([2], ["b"]), ([1], ["c"])],
            "does not identify a single row",
            id="duplicate_across_batches",
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


@pytest.mark.parametrize("value,duplicate", [(-0.0, 0.0), (float("nan"), float("nan"))])
def test_spilled_float_keys_preserve_arrow_equality(value: float, duplicate: float) -> None:
    tracker = UniqueKeyTracker(("key",), max_bytes=1)
    tracker.check(pa.record_batch([[value]], names=["key"]))
    with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
        tracker.check(pa.record_batch([[duplicate]], names=["key"]))
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
