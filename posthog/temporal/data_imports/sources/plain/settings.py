from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updatedAt"
CREATED_AT = "createdAt"
ID = "id"

PLAIN_API_URL = "https://core-api.uk.plain.com/graphql/v1"
PLAIN_DEFAULT_PAGE_SIZE = 100

INCREMENTAL_DATETIME_FIELDS: list[IncrementalField] = [
    {
        "label": UPDATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": UPDATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]

CREATED_AT_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class PlainEndpointConfig:
    incremental_fields: list[IncrementalField]
    primary_key: str = ID
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_AT])


PLAIN_ENDPOINTS: dict[str, PlainEndpointConfig] = {
    "customers": PlainEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "threads": PlainEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "timeline_entries": PlainEndpointConfig(
        incremental_fields=CREATED_AT_INCREMENTAL_FIELD,
        partition_keys=[CREATED_AT],
    ),
}

ENDPOINTS = tuple(PLAIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLAIN_ENDPOINTS.items()
}
