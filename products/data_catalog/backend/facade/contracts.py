"""Cross-product value contracts exposed by data_catalog."""

from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class MetricSummary:
    id: UUID
    name: str
    display_name: str
    definition_kind: str | None
    referenced_table_names: list[str]


@dataclass(frozen=True)
class HogQLMetricDefinition:
    query: str
    values: dict[str, object]


@dataclass(frozen=True)
class MetricRead:
    summary: MetricSummary
    hogql_definition: HogQLMetricDefinition | None
