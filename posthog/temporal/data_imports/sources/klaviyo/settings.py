from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class KlaviyoEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str = "updated_at"
    partition_key: Optional[str] = (
        None  # Field to partition by (should be created_at style field for stable partitions)
    )
    base_filter: Optional[str] = None  # e.g., "equals(messages.channel,'email')"
    page_size: Optional[int] = None  # Override default page size (100)
    sort: Optional[str] = None  # Sort field for the endpoint


KLAVIYO_ENDPOINTS: dict[str, KlaviyoEndpointConfig] = {
    "email_campaigns": KlaviyoEndpointConfig(
        name="email_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'email')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "sms_campaigns": KlaviyoEndpointConfig(
        name="sms_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'sms')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "events": KlaviyoEndpointConfig(
        name="events",
        path="/events",
        default_incremental_field="datetime",
        partition_key="datetime",
        incremental_fields=[
            {
                "label": "datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "flows": KlaviyoEndpointConfig(
        name="flows",
        path="/flows",
        default_incremental_field="updated",
        partition_key="created",
        page_size=50,  # Flows endpoint max is 50
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "lists": KlaviyoEndpointConfig(
        name="lists",
        path="/lists",
        default_incremental_field="updated",
        partition_key="created",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "metrics": KlaviyoEndpointConfig(
        name="metrics",
        path="/metrics",
        page_size=0,  # Metrics endpoint doesn't support pagination
        incremental_fields=[],
    ),
    "profiles": KlaviyoEndpointConfig(
        name="profiles",
        path="/profiles",
        default_incremental_field="updated",
        partition_key="created",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(KLAVIYO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KLAVIYO_ENDPOINTS.items()
}
