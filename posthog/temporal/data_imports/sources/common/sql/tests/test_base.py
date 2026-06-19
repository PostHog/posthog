from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock

from posthog.schema import SourceConfig

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.common.sql.implementation import SourceMetadata, SQLSourceImplementation
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalFieldType


@dataclasses.dataclass
class _FakeConfig(Config):
    name: str = "fake"


def _fake_filter(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Treat any column typed 'timestamp' as incremental-capable."""
    return [
        (name, IncrementalFieldType.Timestamp, nullable)
        for name, data_type, nullable in columns
        if data_type == "timestamp"
    ]


@dataclasses.dataclass
class _FakeImplData:
    columns_by_table: dict[str, list[tuple[str, str, bool]]] = dataclasses.field(default_factory=dict)
    primary_keys_by_table: dict[str, list[str] | None] = dataclasses.field(default_factory=dict)
    row_counts_by_table: dict[str, int | None] = dataclasses.field(default_factory=dict)
    foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = dataclasses.field(default_factory=dict)
    source_metadata: SourceMetadata = dataclasses.field(default_factory=SourceMetadata)
    cdc_by_table: dict[str, bool] = dataclasses.field(default_factory=dict)


class _FakeImplementation(SQLSourceImplementation[_FakeConfig, object, Any]):
    """Records the arguments it receives so tests can assert on the wiring."""

    def __init__(self, data: _FakeImplData | None = None) -> None:
        self.data = data or _FakeImplData()
        self.get_columns_calls: list[tuple[list[str] | None]] = []
        self.get_primary_keys_called = False
        self.get_row_counts_called = False
        self.get_foreign_keys_called = False

    @contextmanager
    def connect(self, config: _FakeConfig):
        yield object()

    def get_columns(
        self, conn: object, config: _FakeConfig, names: list[str] | None
    ) -> dict[str, list[tuple[str, str, bool]]]:
        self.get_columns_calls.append((names,))
        if names is None:
            return self.data.columns_by_table
        return {k: v for k, v in self.data.columns_by_table.items() if k in names}

    def get_primary_keys(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, list[str] | None]:
        self.get_primary_keys_called = True
        return self.data.primary_keys_by_table

    def get_row_counts(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, int | None]:
        self.get_row_counts_called = True
        return self.data.row_counts_by_table

    def get_foreign_keys(
        self, conn: object, config: _FakeConfig, tables: list[str]
    ) -> dict[str, list[tuple[str, str, str]]]:
        self.get_foreign_keys_called = True
        return self.data.foreign_keys_by_table

    def get_source_metadata(self, conn: object, config: _FakeConfig, tables: list[str]) -> SourceMetadata:
        return self.data.source_metadata

    def get_cdc_support(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, bool]:
        return self.data.cdc_by_table

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return _fake_filter

    def build_pipeline(self, config: _FakeConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError("not exercised in get_schemas tests")


class _FakeSQLSource(SQLSource[_FakeConfig]):
    def __init__(self, impl: _FakeImplementation) -> None:
        self._implementation = impl

    @property
    def get_implementation(self) -> _FakeImplementation:
        return self._implementation

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTGRES

    @property
    def get_source_config(self) -> SourceConfig:
        return MagicMock(spec=SourceConfig)


def _make_source(**data: Any) -> tuple[_FakeSQLSource, _FakeImplementation]:
    impl = _FakeImplementation(_FakeImplData(**data))
    return _FakeSQLSource(impl), impl


class TestGetSchemas:
    def test_returns_one_source_schema_per_table(self) -> None:
        source, _ = _make_source(
            columns_by_table={
                "messages": [("id", "int", False), ("ts", "timestamp", False)],
                "users": [("id", "int", False)],
            }
        )
        result = source.get_schemas(_FakeConfig(), team_id=1)
        assert {s.name for s in result} == {"messages", "users"}

    def test_incremental_fields_derived_via_filter(self) -> None:
        source, _ = _make_source(columns_by_table={"messages": [("id", "int", False), ("ts", "timestamp", False)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        fields: list[Any] = list(schema.incremental_fields)
        assert len(fields) == 1
        assert fields[0]["field"] == "ts"
        assert schema.supports_incremental is True
        assert schema.supports_append is True

    def test_no_incremental_fields_disables_incremental_flags(self) -> None:
        source, _ = _make_source(columns_by_table={"tbl": [("id", "int", False)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.incremental_fields == []
        assert schema.supports_incremental is False

    def test_detected_primary_keys_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            primary_keys_by_table={"messages": ["id"]},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_falls_back_to_id_column_when_no_pk_detected(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False), ("body", "text", True)]},
            primary_keys_by_table={"messages": None},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_no_pk_fallback_when_no_id_column(self) -> None:
        source, _ = _make_source(columns_by_table={"messages": [("body", "text", True)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys is None

    def test_row_counts_passed_through_when_with_counts_true(self) -> None:
        source, impl = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            row_counts_by_table={"messages": 42},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1, with_counts=True)
        assert schema.row_count == 42
        assert impl.get_row_counts_called is True

    def test_row_counts_skipped_when_with_counts_false(self) -> None:
        source, impl = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            row_counts_by_table={"messages": 42},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1, with_counts=False)
        assert schema.row_count is None
        assert impl.get_row_counts_called is False

    def test_foreign_keys_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            foreign_keys_by_table={"messages": [("author_id", "users", "id")]},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.foreign_keys == [("author_id", "users", "id")]

    @pytest.mark.parametrize("names", [None, ["messages"]])
    def test_names_forwarded_to_get_columns(self, names: list[str] | None) -> None:
        source, impl = _make_source(
            columns_by_table={
                "messages": [("id", "int", False)],
                "users": [("id", "int", False)],
            }
        )
        source.get_schemas(_FakeConfig(), team_id=1, names=names)
        assert impl.get_columns_calls == [(names,)]

    def test_empty_discovery_returns_empty_list(self) -> None:
        source, _ = _make_source(columns_by_table={})
        assert source.get_schemas(_FakeConfig(), team_id=1) == []

    def test_source_metadata_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"t": [("id", "int", False)]},
            source_metadata=SourceMetadata(
                catalog_by_table={"t": "my_db"},
                schema_by_table={"t": "public"},
                table_name_by_table={"t": "original_t"},
            ),
            cdc_by_table={"t": True},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.source_catalog == "my_db"
        assert schema.source_schema == "public"
        assert schema.source_table_name == "original_t"
        assert schema.supports_cdc is True


class TestDefaultNonRetryableErrors:
    @pytest.mark.parametrize(
        "key,expected_substring",
        [
            ("Source column type changed", "reset and fully re-sync"),
            ("Cannot build decimal array from values", "decimal storage limits"),
        ],
    )
    def test_includes_expected_entry(self, key: str, expected_substring: str) -> None:
        # Calling without an instance proves the classmethod shape too — the
        # eventual subclass call site is `cls.default_non_retryable_errors()`.
        errors = SQLSource.default_non_retryable_errors()
        assert key in errors
        message = errors[key]
        assert message is not None
        assert expected_substring in message

    def test_returns_exactly_the_two_shared_entries(self) -> None:
        errors = SQLSource.default_non_retryable_errors()
        assert isinstance(errors, dict)
        assert len(errors) == 2
