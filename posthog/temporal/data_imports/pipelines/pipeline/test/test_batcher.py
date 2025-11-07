import pytest
from unittest import mock

import pyarrow as pa

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher


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
