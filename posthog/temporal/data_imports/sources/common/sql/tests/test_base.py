from __future__ import annotations

import dataclasses
from typing import Any

from unittest.mock import MagicMock

from posthog.schema import SourceConfig

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.sources.common.sql.base import DiscoveryResult, SQLSource
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


class _FakeSQLSource(SQLSource[_FakeConfig]):
    """Minimal concrete subclass used to exercise template-method wiring."""

    source_display_name = "Fake DB"

    def __init__(self, *, discovery: DiscoveryResult | None = None) -> None:
        self._discovery = discovery or DiscoveryResult(columns_by_table={})
        self._pipeline_calls: list[tuple[_FakeConfig, SourceInputs]] = []
        self._last_discover_args: tuple[list[str] | None, bool] | None = None

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTGRES

    @property
    def get_source_config(self) -> SourceConfig:
        return MagicMock(spec=SourceConfig)

    def _discover(self, config: _FakeConfig, names: list[str] | None, with_counts: bool) -> DiscoveryResult:
        self._last_discover_args = (names, with_counts)
        if names is None:
            return self._discovery
        filtered_cols = {k: v for k, v in self._discovery.columns_by_table.items() if k in names}
        return dataclasses.replace(self._discovery, columns_by_table=filtered_cols)

    def _filter_incremental_fields(self) -> IncrementalFieldFilter:
        return _fake_filter

    def _run_pipeline_source(self, config: _FakeConfig, inputs: SourceInputs) -> SourceResponse:
        self._pipeline_calls.append((config, inputs))
        return SourceResponse(name=inputs.schema_name, items=lambda: iter([]), primary_keys=None)


def _inputs(schema_name: str = "messages") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestGetSchemas:
    def test_returns_one_source_schema_per_table(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={
                    "messages": [("id", "int", False), ("ts", "timestamp", False)],
                    "users": [("id", "int", False)],
                }
            )
        )
        result = source.get_schemas(_FakeConfig(), team_id=1)
        assert {s.name for s in result} == {"messages", "users"}

    def test_incremental_fields_derived_via_filter(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(columns_by_table={"messages": [("id", "int", False), ("ts", "timestamp", False)]})
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        fields: list[Any] = list(schema.incremental_fields)
        assert len(fields) == 1
        assert fields[0]["field"] == "ts"
        assert schema.supports_incremental is True
        assert schema.supports_append is True

    def test_no_incremental_fields_disables_incremental_flags(self) -> None:
        source = _FakeSQLSource(discovery=DiscoveryResult(columns_by_table={"tbl": [("id", "int", False)]}))
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.incremental_fields == []
        assert schema.supports_incremental is False

    def test_detected_primary_keys_passed_through(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={"messages": [("id", "int", False)]},
                primary_keys_by_table={"messages": ["id"]},
            )
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_falls_back_to_id_column_when_no_pk_detected(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={"messages": [("id", "int", False), ("body", "text", True)]},
                primary_keys_by_table={"messages": None},
            )
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_no_pk_fallback_when_no_id_column(self) -> None:
        source = _FakeSQLSource(discovery=DiscoveryResult(columns_by_table={"messages": [("body", "text", True)]}))
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys is None

    def test_row_counts_passed_through_when_present(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={"messages": [("id", "int", False)]},
                row_counts_by_table={"messages": 42},
            )
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1, with_counts=True)
        assert schema.row_count == 42

    def test_foreign_keys_passed_through(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={"messages": [("id", "int", False)]},
                foreign_keys_by_table={"messages": [("author_id", "users", "id")]},
            )
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.foreign_keys == [("author_id", "users", "id")]

    def test_with_counts_flag_forwarded_to_discover(self) -> None:
        source = _FakeSQLSource(discovery=DiscoveryResult(columns_by_table={"tbl": [("id", "int", False)]}))
        source.get_schemas(_FakeConfig(), team_id=1, with_counts=True)
        assert source._last_discover_args == (None, True)
        source.get_schemas(_FakeConfig(), team_id=1, with_counts=False)
        assert source._last_discover_args == (None, False)

    def test_names_filter_forwarded_to_discover(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={
                    "messages": [("id", "int", False)],
                    "users": [("id", "int", False)],
                }
            )
        )
        result = source.get_schemas(_FakeConfig(), team_id=1, names=["messages"])
        assert [s.name for s in result] == ["messages"]
        assert source._last_discover_args == (["messages"], False)

    def test_empty_discovery_returns_empty_list(self) -> None:
        source = _FakeSQLSource(discovery=DiscoveryResult(columns_by_table={}))
        assert source.get_schemas(_FakeConfig(), team_id=1) == []

    def test_source_metadata_passed_through(self) -> None:
        source = _FakeSQLSource(
            discovery=DiscoveryResult(
                columns_by_table={"t": [("id", "int", False)]},
                source_catalog_by_table={"t": "my_db"},
                source_schema_by_table={"t": "public"},
                source_table_name_by_table={"t": "original_t"},
                supports_cdc_by_table={"t": True},
            )
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.source_catalog == "my_db"
        assert schema.source_schema == "public"
        assert schema.source_table_name == "original_t"
        assert schema.supports_cdc is True


class TestSourceForPipeline:
    def test_delegates_to_run_pipeline_source(self) -> None:
        source = _FakeSQLSource(discovery=DiscoveryResult(columns_by_table={"messages": [("id", "int", False)]}))
        response = source.source_for_pipeline(_FakeConfig(), _inputs("messages"))
        assert response.name == "messages"
        assert len(source._pipeline_calls) == 1
