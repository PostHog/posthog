"""UniqueKeyTracker in isolation: pure pyarrow, no database, no delta table.

The activity-level suite proves the tracker is wired into both write paths; these cover the
detection logic itself, where the cheap edge cases live (composite keys, the byte cap, a key
column missing from the output).
"""

import pytest

import pyarrow as pa

from posthog.temporal.data_modeling.activities.incremental_write import IncrementalWriteError, UniqueKeyTracker


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
def test_single_column_violations_are_detected(batches: list[tuple], match: str) -> None:
    tracker = UniqueKeyTracker(("id",))

    with pytest.raises(IncrementalWriteError, match=match):
        for ids, names in batches:
            tracker.check(_batch(ids, names))


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
    tracker = UniqueKeyTracker(("id",), max_bytes=8)

    with pytest.raises(IncrementalWriteError, match="too many unique keys"):
        tracker.check(_batch([1, 2, 3, 4], ["a", "b", "c", "d"]))
