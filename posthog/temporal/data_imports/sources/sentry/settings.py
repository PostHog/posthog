from dataclasses import dataclass
from typing import Literal, Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SentryEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str = "id"


SENTRY_ENDPOINTS: dict[str, SentryEndpointConfig] = {
    "projects": SentryEndpointConfig(
        name="projects",
        path="/organizations/{organization_slug}/projects/",
        incremental_fields=[],
    ),
    "issues": SentryEndpointConfig(
        name="issues",
        path="/organizations/{organization_slug}/issues/",
        incremental_fields=[
            {
                "label": "lastSeen",
                "type": IncrementalFieldType.DateTime,
                "field": "lastSeen",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "firstSeen",
                "type": IncrementalFieldType.DateTime,
                "field": "firstSeen",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="lastSeen",
        partition_key="lastSeen",
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(SENTRY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENTRY_ENDPOINTS.items()
}
