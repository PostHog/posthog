from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

NOTION_API_URL = "https://api.notion.com/v1"
# Pinned per Notion's API versioning model — the same version must be sent on every
# request (OAuth handshake and subsequent API calls). Bumping this is a deliberate
# API-level migration, so we keep it as a constant rather than reading it from env.
# https://developers.notion.com/reference/versioning
NOTION_API_VERSION = "2026-03-11"
# Notion's documented maximum for `page_size` across endpoints that accept it.
NOTION_DEFAULT_PAGE_SIZE = 100

ID = "id"
CREATED_TIME = "created_time"
LAST_EDITED_TIME = "last_edited_time"

# Endpoint name for the dynamic per-data-source row tables. Real schema names are
# `data_source_rows__{data_source_id_no_hyphens}` — this prefix lets the source
# dispatcher tell row schemas apart from the static ones.
DATA_SOURCE_ROWS_PREFIX = "data_source_rows__"

INCREMENTAL_DATETIME_FIELDS: list[IncrementalField] = [
    {
        "label": LAST_EDITED_TIME,
        "type": IncrementalFieldType.DateTime,
        "field": LAST_EDITED_TIME,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class NotionEndpointConfig:
    incremental_fields: list[IncrementalField]
    primary_key: str = ID
    partition_count: int = 1
    partition_size: int = 1
    # Use created_time, never last_edited_time — partition keys must be stable.
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_TIME])


# Static endpoints shared by every Notion source instance. Data-source row tables are
# discovered at runtime from `/v1/search?filter=data_source` and configured per-data-source.
NOTION_STATIC_ENDPOINTS: dict[str, NotionEndpointConfig] = {
    "users": NotionEndpointConfig(
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "pages": NotionEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "data_sources": NotionEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
}

STATIC_ENDPOINTS = tuple(NOTION_STATIC_ENDPOINTS.keys())


def data_source_rows_endpoint_config() -> NotionEndpointConfig:
    """Per-data-source row table — incremental on last_edited_time, partitioned by created_time."""
    return NotionEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    )


def data_source_rows_schema_name(data_source_id: str) -> str:
    """Build a stable schema name for a Notion data source's row table.

    Notion data source IDs are UUIDs (with or without hyphens). We strip hyphens to keep
    the schema name SQL-friendly while still uniquely identifying the source.
    """
    return f"{DATA_SOURCE_ROWS_PREFIX}{data_source_id.replace('-', '')}"
