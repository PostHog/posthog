"""Tests for the `SchemaExplorer` base class.

These cover the *shared* math (partition sizing, chunk sizing) that the base
class provides. Driver-specific query behavior is tested next to each
explorer implementation (e.g. `mysql/tests/test_schema_explorer.py`).
"""

from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import MagicMock

from posthog.temporal.data_imports.sources.common.sql import SchemaExplorer, Table, TableStats
from posthog.temporal.data_imports.sources.common.sql.types import Column


class _FakeColumn(Column):
    def __init__(self, name: str) -> None:
        self.name = name

    def to_arrow_field(self):  # pragma: no cover — not exercised by these tests
        raise NotImplementedError


class _FakeExplorer(SchemaExplorer[Any, _FakeColumn]):
    """Minimal `SchemaExplorer` that lets tests drive the base-class math directly."""

    def __init__(
        self,
        *,
        stats: TableStats | None = None,
        raises_on_stats: bool = False,
        row_size: int | None = None,
        raises_on_row_size: bool = False,
    ) -> None:
        self._stats = stats
        self._raises_on_stats = raises_on_stats
        self._row_size = row_size
        self._raises_on_row_size = raises_on_row_size
        self.fetch_table_stats_calls: list[tuple[Any, ...]] = []
        self.fetch_average_row_size_calls: list[tuple[Any, ...]] = []

    def get_primary_keys(self, cursor, schema, table_name):  # pragma: no cover
        return None

    def get_table(self, cursor, schema, table_name):  # pragma: no cover
        return Table(name=table_name, parents=(schema,), columns=[])

    def get_rows_to_sync(self, cursor, inner_query, inner_query_args, logger):  # pragma: no cover
        return 0

    def fetch_table_stats(self, cursor, schema, table_name, logger):
        self.fetch_table_stats_calls.append((cursor, schema, table_name))
        if self._raises_on_stats:
            raise RuntimeError("stats query blew up")
        return self._stats

    def fetch_average_row_size(self, cursor, schema, table_name, inner_query, inner_query_args, logger):
        self.fetch_average_row_size_calls.append((cursor, schema, table_name, inner_query, inner_query_args))
        if self._raises_on_row_size:
            raise RuntimeError("row size query blew up")
        return self._row_size

    def find_index_for_cursor(self, cursor, schema, table_name, cursor_field, logger):  # pragma: no cover
        return None


@pytest.fixture
def logger():
    return MagicMock()


class TestGetPartitionSettings:
    def test_returns_none_when_stats_missing(self, logger):
        explorer = _FakeExplorer(stats=None)
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger)
        assert result is None

    def test_returns_none_when_table_empty(self, logger):
        explorer = _FakeExplorer(stats=TableStats(table_size_bytes=0, row_count=0))
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger)
        assert result is None

    def test_returns_none_when_fetch_raises(self, logger):
        explorer = _FakeExplorer(raises_on_stats=True)
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger)
        assert result is None
        # We still called through to the driver hook.
        assert explorer.fetch_table_stats_calls == [(explorer.fetch_table_stats_calls[0])]

    def test_single_partition_fallback_when_partition_count_is_zero(self, logger):
        # Tiny table: 100 bytes, 2 rows → avg_row_size = 50 → partition_size huge
        # → floor(2 / big) = 0 → we fall back to 1 partition.
        explorer = _FakeExplorer(stats=TableStats(table_size_bytes=100, row_count=2))
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger)
        assert result is not None
        assert result.partition_count == 1
        # partition_size = round(default_target / 50), which for default 500MB is huge
        assert result.partition_size > 1

    def test_computes_partition_settings_from_stats(self, logger):
        # 1M rows * 100 bytes/row = 100MB. With partition_size_bytes=1MB,
        # partition_size = round(1_000_000 / 100) = 10_000 rows per partition,
        # partition_count = floor(1_000_000 / 10_000) = 100.
        explorer = _FakeExplorer(stats=TableStats(table_size_bytes=100_000_000, row_count=1_000_000))
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger, partition_size_bytes=1_000_000)
        assert result is not None
        assert result.partition_size == 10_000
        assert result.partition_count == 100

    def test_partition_size_never_below_one(self, logger):
        # Pathological: huge rows. avg_row_size = 10**12 → partition_size
        # = round(1e6 / 1e12) = 0 but code clamps to 1.
        explorer = _FakeExplorer(stats=TableStats(table_size_bytes=10**15, row_count=1000))
        result = explorer.get_partition_settings(MagicMock(), "db", "t", logger, partition_size_bytes=1_000_000)
        assert result is not None
        assert result.partition_size >= 1

    def test_passes_through_schema_and_table(self, logger):
        explorer = _FakeExplorer(stats=None)
        cursor = MagicMock()
        explorer.get_partition_settings(cursor, "mydb", "mytable", logger)
        assert explorer.fetch_table_stats_calls == [(cursor, "mydb", "mytable")]


class TestGetChunkSize:
    @pytest.mark.parametrize(
        "row_size,target_size,expected",
        [
            (100, 1_000_000, 10_000),  # happy path
            (1, 1_000_000, 1_000_000),  # tiny rows
            (10**9, 1_000, 1),  # huge rows clamped to 1
        ],
    )
    def test_computes_chunk_size_from_row_size(self, logger, row_size, target_size, expected):
        explorer = _FakeExplorer(row_size=row_size)
        result = explorer.get_chunk_size(
            MagicMock(), "db", "t", "SELECT 1", {}, logger, target_chunk_size_bytes=target_size
        )
        assert result == expected

    def test_falls_back_to_default_on_none(self, logger):
        explorer = _FakeExplorer(row_size=None)
        result = explorer.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=42)
        assert result == 42

    def test_falls_back_to_default_on_zero(self, logger):
        explorer = _FakeExplorer(row_size=0)
        result = explorer.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=77)
        assert result == 77

    def test_falls_back_to_default_on_exception(self, logger):
        explorer = _FakeExplorer(raises_on_row_size=True)
        result = explorer.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=99)
        assert result == 99

    def test_passes_inner_query_through(self, logger):
        explorer = _FakeExplorer(row_size=500)
        cursor = MagicMock()
        explorer.get_chunk_size(cursor, "db", "t", "SELECT x FROM y", {"a": 1}, logger)
        assert explorer.fetch_average_row_size_calls == [(cursor, "db", "t", "SELECT x FROM y", {"a": 1})]
