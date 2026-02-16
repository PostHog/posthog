from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updatedAt"
CREATED_AT = "createdAt"
ID = "id"

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_DEFAULT_PAGE_SIZE = 250

INCREMENTAL_DATETIME_FIELDS: list[IncrementalField] = [
    {
        "label": UPDATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": UPDATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class LinearEndpointConfig:
    incremental_fields: list[IncrementalField]
    graphql_query_name: str | None = None
    primary_key: str = ID
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_AT])


LINEAR_ENDPOINTS: dict[str, LinearEndpointConfig] = {
    "issues": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "projects": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "teams": LinearEndpointConfig(
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "users": LinearEndpointConfig(
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "comments": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "labels": LinearEndpointConfig(
        graphql_query_name="issueLabels",
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "cycles": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "resources": LinearEndpointConfig(
        graphql_query_name="attachments",
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
}

ENDPOINTS = tuple(LINEAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINEAR_ENDPOINTS.items()
}
