from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updated_at"
CREATED_AT = "created_at"
ID = "id"

BUILDBETTER_API_URL = "https://api.buildbetter.app/v1/graphql"
BUILDBETTER_DEFAULT_PAGE_SIZE = 1000

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
    graphql_query_name: str | None = None
    page_size: int = BUILDBETTER_DEFAULT_PAGE_SIZE
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
        page_size=100,
        partition_keys=[CREATED_AT],
    ),
    "extractions": BuildBetterEndpointConfig(
        graphql_query_name="extraction",
        incremental_fields=INCREMENTAL_CREATED_AT,
        partition_keys=[CREATED_AT],
    ),
    "persons": BuildBetterEndpointConfig(
        graphql_query_name="person",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "companies": BuildBetterEndpointConfig(
        graphql_query_name="company",
        incremental_fields=INCREMENTAL_UPDATED_AT,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
}

ENDPOINTS = tuple(BUILDBETTER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUILDBETTER_ENDPOINTS.items()
}
