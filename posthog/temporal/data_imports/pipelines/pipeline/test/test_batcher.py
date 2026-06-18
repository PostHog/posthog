import pytest
from unittest import mock

import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.batcher import (
    Batcher,
    _column_offset_pressure,
    _max_offset_pressure,
    _split_to_offset_limit,
)


def _drain(batcher: Batcher) -> list[pa.Table]:
    tables = []
    while batcher.should_yield(include_incomplete_chunk=True):
        tables.append(batcher.get_table())
    return tables


def test_batching_pa_table_should_yield():
    batcher = Batcher(logger=mock.MagicMock())

    pa_table = pa.table(
        {
            "column1": [1, 2, 3],
            "column2": ["a", "b", "c"],
        }
    )

    batcher.batch(pa_table)

    assert batcher.should_yield() is True

    result_table = batcher.get_table()

    assert result_table.equals(pa_table)


def test_batching_multiple_pa_tables_should_raise():
    batcher = Batcher(logger=mock.MagicMock())

    pa_table1 = pa.table(
        {
            "column1": [1, 2, 3],
            "column2": ["a", "b", "c"],
        }
    )

    pa_table2 = pa.table(
        {
            "column1": [4, 5, 6],
            "column2": ["d", "e", "f"],
        }
    )

    batcher.batch(pa_table1)

    with pytest.raises(Exception) as exc_info:
        batcher.batch(pa_table2)

    assert (
        str(exc_info.value)
        == "Batcher already has a table ready to yield. Call get_table() before batching more items."
    )


def test_batching_lists_should_yield_after_chunk_size_threshold():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=3)

    list_data = [{"a": 1}, {"a": 2}, {"a": 3}]
    batcher.batch(list_data)

    assert batcher.should_yield() is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": [1, 2, 3]})

    assert result_table.equals(expected_table)


def test_batching_lists_should_yield_after_chunk_size_bytes_threshold():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size_bytes=1)

    batcher.batch([{"a": "x"}, {"a": "y"}])

    assert batcher.should_yield() is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": ["x", "y"]})

    assert result_table.equals(expected_table)


@parameterized.expand(
    [
        ("string", pa.array(["aa", "bb", "cc", "dd"], type=pa.string()), 8),
        ("binary", pa.array([b"aa", b"bb"], type=pa.binary()), 4),
        ("list", pa.array([[1, 2], [3], [4, 5, 6]], type=pa.list_(pa.int64())), 6),
        ("large_string_is_safe", pa.array(["aa", "bb"], type=pa.large_string()), 0),
        ("int_is_safe", pa.array([1, 2, 3], type=pa.int64()), 0),
        ("nulls_counted_as_zero", pa.array([None, "abc", None], type=pa.string()), 3),
    ]
)
def test_column_offset_pressure(_name: str, array: pa.Array, expected: int):
    assert _column_offset_pressure(pa.chunked_array([array])) == expected


def test_max_offset_pressure_picks_worst_column():
    table = pa.table(
        {
            "small": pa.array(["a", "b"], type=pa.string()),
            "big": pa.array(["aaaa", "bbbb"], type=pa.string()),
            "ints": pa.array([1, 2], type=pa.int64()),
        }
    )

    assert _max_offset_pressure(table) == 8


def test_split_to_offset_limit_under_limit_is_noop():
    table = pa.table({"a": ["x", "y", "z"]})

    result = _split_to_offset_limit(table, limit=1_000)

    assert len(result) == 1
    assert result[0].equals(table)


def test_split_to_offset_limit_splits_and_preserves_data_and_order():
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    # Total "val" bytes = 8; limit 3 forces splitting until each slice is <= 3 bytes.
    result = _split_to_offset_limit(table, limit=3)

    assert len(result) > 1
    for slice_table in result:
        assert _max_offset_pressure(slice_table) <= 3
    # Concatenating the slices reproduces the original table in order.
    assert pa.concat_tables(result).equals(table)


def test_split_to_offset_limit_single_row_never_splits():
    # A single row can't be split further even if it exceeds the limit.
    table = pa.table({"val": ["a-very-long-value"]})

    result = _split_to_offset_limit(table, limit=1)

    assert len(result) == 1
    assert result[0].equals(table)


def test_batcher_splits_oversized_pa_table_on_yield():
    batcher = Batcher(logger=mock.MagicMock(), max_column_offset_bytes=3)
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) > 1
    assert pa.concat_tables(drained).equals(table)


def test_batcher_does_not_split_when_under_limit():
    batcher = Batcher(logger=mock.MagicMock(), max_column_offset_bytes=1_000_000)
    table = pa.table({"id": [0, 1, 2, 3], "val": ["aa", "bb", "cc", "dd"]})

    batcher.batch(table)

    drained = _drain(batcher)

    assert len(drained) == 1
    assert drained[0].equals(table)


def test_batcher_splits_buffered_list_items():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=4, max_column_offset_bytes=3)

    batcher.batch([{"val": "aa"}, {"val": "bb"}, {"val": "cc"}, {"val": "dd"}])

    drained = _drain(batcher)

    assert len(drained) > 1
    combined = pa.concat_tables(drained)
    assert combined.column("val").to_pylist() == ["aa", "bb", "cc", "dd"]


def test_batching_should_not_yield_when_buffer_not_full():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=5, chunk_size_bytes=1000)

    batcher.batch([{"a": 1}, {"a": 2}])

    assert batcher.should_yield() is False


def test_batching_should_yield_when_buffer_not_full_with_incomplete_chunk_set():
    batcher = Batcher(logger=mock.MagicMock(), chunk_size=50, chunk_size_bytes=10000)

    batcher.batch({"a": 1})
    batcher.batch({"a": 2})
    batcher.batch({"a": 3})

    assert batcher.should_yield(include_incomplete_chunk=False) is False
    assert batcher.should_yield(include_incomplete_chunk=True) is True

    result_table = batcher.get_table()
    expected_table = pa.table({"a": [1, 2, 3]})

    assert result_table.equals(expected_table)
