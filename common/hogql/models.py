from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class HogLanguage(StrEnum):
    HOG = "hog"
    HOG_JSON = "hogJson"
    HOG_QL = "hogQL"
    HOG_QL_EXPR = "hogQLExpr"
    HOG_TEMPLATE = "hogTemplate"
    LIQUID = "liquid"


@dataclass(slots=True)
class HogQLMetadataRequest:
    language: str
    query: str
    kind: str = "HogQLMetadata"
    response: Any | None = None
    modifiers: Any | None = None
    filters: Any | None = None
    globals: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    sourceQuery: Any | None = None
    connectionId: str | None = None
    debug: bool | None = None


@dataclass(slots=True)
class HogQLMetadataResponse(dict):
    errors: list[Any]
    notices: list[Any]
    warnings: list[Any]
    ch_table_names: list[str] | None = None
    isUsingIndices: Any | None = None
    isValid: bool | None = None
    query: str | None = None
    table_names: list[str] | None = None

    def __post_init__(self) -> None:
        dict.__init__(self, **self.model_dump())

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ch_table_names": self.ch_table_names,
            "errors": self.errors,
            "isUsingIndices": self.isUsingIndices,
            "isValid": self.isValid,
            "notices": self.notices,
            "query": self.query,
            "table_names": self.table_names,
            "warnings": self.warnings,
        }

    def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.model_dump(*args, **kwargs)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, **kwargs: Any) -> HogQLMetadataResponse:
        return replace(self, **dict(update or {}))


@dataclass(slots=True)
class HogQLQueryResponse(dict):
    results: list[Any]
    clickhouse: str | None = None
    columns: list[Any] | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | Any | None = None
    modifiers: Any | None = None
    offset: int | None = None
    query: Any | None = None
    query_status: Any | None = None
    resolved_compare_date_range: Any | None = None
    resolved_date_range: Any | None = None
    timings: list[Any] | None = None
    types: list[Any] | None = None
    warnings: list[Any] | None = None

    def __post_init__(self) -> None:
        dict.__init__(self, **self.model_dump())

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "clickhouse": self.clickhouse,
            "columns": self.columns,
            "error": self.error,
            "explain": self.explain,
            "hasMore": self.hasMore,
            "hogql": self.hogql,
            "limit": self.limit,
            "metadata": self.metadata,
            "modifiers": self.modifiers,
            "offset": self.offset,
            "query": self.query,
            "query_status": self.query_status,
            "resolved_compare_date_range": self.resolved_compare_date_range,
            "resolved_date_range": self.resolved_date_range,
            "results": self.results,
            "timings": self.timings,
            "types": self.types,
            "warnings": self.warnings,
        }

    def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.model_dump(*args, **kwargs)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, **kwargs: Any) -> HogQLQueryResponse:
        return replace(self, **dict(update or {}))
