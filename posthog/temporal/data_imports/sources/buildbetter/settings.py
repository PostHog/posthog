from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updated_at"
CREATED_AT = "created_at"
ID = "id"

BUILDBETTER_API_URL = "https://api.buildbetter.app/v1/graphql"
BUILDBETTER_DEFAULT_PAGE_SIZE = 100

INCREMENTAL_UPDATED_AT: list[IncrementalField] = [
    {
        "label": UPDATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": UPDATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]

INCREMENTAL_CREATED_AT: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class BuildBetterEndpointConfig:
    incremental_fields: list[IncrementalField]
    incremental_filter_field: str | None = None
    graphql_query_name: str | None = None
    primary_key: str = ID
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_AT])


BUILDBETTER_ENDPOINTS: dict[str, BuildBetterEndpointConfig] = {
    "interviews": BuildBetterEndpointConfig(
        graphql_query_name="interview",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        incremental_filter_field=UPDATED_AT,
        partition_keys=[CREATED_AT],
    ),
    "extractions": BuildBetterEndpointConfig(
        graphql_query_name="extraction",
        incremental_fields=INCREMENTAL_CREATED_AT,
        incremental_filter_field=CREATED_AT,
        partition_keys=[CREATED_AT],
    ),
}

ENDPOINTS = tuple(BUILDBETTER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUILDBETTER_ENDPOINTS.items()
}
