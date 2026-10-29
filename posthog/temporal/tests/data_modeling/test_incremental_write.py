"""UniqueKeyTracker in isolation: pure pyarrow, no database, no delta table.

The activity-level suite proves the tracker is wired into both write paths; these cover the
detection logic itself, where the cheap edge cases live (composite keys, the byte cap, a key
column missing from the output).
"""

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from posthog.temporal.data_modeling.activities.incremental_write import (
    MAX_UNIQUE_KEY_CHECK_BYTES,
    IncrementalWriteError,
    UniqueKeyTracker,
    upsert_batch,
)


def _batch(ids: list[int | None], names: list[str | None]) -> pa.RecordBatch:
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
        pytest.param([([1, None], ["a", "b"])], "is null", id="null_key"),
    ],
)
def test_single_column_violations_are_detected(batches: list[tuple], match: str) -> None:
    tracker = UniqueKeyTracker(("id",))

    with pytest.raises(IncrementalWriteError, match=match):
        for ids, names in batches:
            tracker.check(_batch(ids, names))


def test_a_duplicate_split_across_slices_of_one_batch_is_detected() -> None:
    tracker = UniqueKeyTracker(("id",))

    with patch("posthog.temporal.data_modeling.activities.incremental_write.UNIQUE_KEY_CHECK_SLICE_ROWS", 2):
        with pytest.raises(IncrementalWriteError, match="appears 2 times"):
            tracker.check(_batch([1, 2, 3, 1], ["a", "b", "c", "d"]))


def test_distinct_keys_across_batches_pass() -> None:
    tracker = UniqueKeyTracker(("id",))

    tracker.check(_batch([1, 2], ["a", "b"]))
    tracker.check(_batch([3, 4], ["c", "d"]))


def test_composite_key_is_checked_as_a_tuple() -> None:
    """Columns may repeat individually; only the full tuple repeating is a violation."""
    tracker = UniqueKeyTracker(("id", "name"))

    tracker.check(_batch([1, 1], ["a", "b"]))
    tracker.check(_batch([2, 2], ["a", "b"]))

    with pytest.raises(IncrementalWriteError, match="does not identify a single row"):
        tracker.check(_batch([1], ["a"]))


def test_a_missing_key_column_names_the_column() -> None:
    tracker = UniqueKeyTracker(("missing",))

    with pytest.raises(IncrementalWriteError, match="missing"):
        tracker.check(_batch([1], ["a"]))


def test_exceeding_the_memory_cap_fails_loudly() -> None:
    """The cap must fail the run, never silently stop checking."""
    tracker = UniqueKeyTracker(("id",), max_bytes=24)
    tracker.check(_batch([1, 2], ["a", "b"]))

    with pytest.raises(IncrementalWriteError, match=r"too many unique keys to verify \(4 so far\)"):
        tracker.check(_batch([3, 4], ["c", "d"]))


def test_the_cap_admits_a_seven_million_key_uuid_run() -> None:
    sample = 10_000
    ids = pa.array(np.arange(sample, dtype=np.int64))
    uuid_sized = pa.table({"id": pc.utf8_lpad(pc.cast(ids, pa.string()), width=36, padding="0")})

    assert uuid_sized.nbytes * (7_000_000 // sample) <= MAX_UNIQUE_KEY_CHECK_BYTES


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
