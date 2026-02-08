from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PolarEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str = "created_at"
    partition_key: Optional[str] = None
    page_size: Optional[int] = 100
    sort: Optional[str] = None


POLAR_ENDPOINTS: dict[str, PolarEndpointConfig] = {
    "customers": PolarEndpointConfig(
        name="customers",
        path="/customers/",
        partition_key="created_at",
        sort="-created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "products": PolarEndpointConfig(
        name="products",
        path="/products/",
        partition_key="created_at",
        sort="-created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "orders": PolarEndpointConfig(
        name="orders",
        path="/orders/",
        partition_key="created_at",
        sort="-created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "subscriptions": PolarEndpointConfig(
        name="subscriptions",
        path="/subscriptions/",
        partition_key="created_at",
        default_incremental_field="started_at",
        sort="-started_at",
        incremental_fields=[
            {
                "label": "started_at",
                "type": IncrementalFieldType.DateTime,
                "field": "started_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "events": PolarEndpointConfig(
        name="events",
        path="/events/",
        partition_key="timestamp",
        default_incremental_field="timestamp",
        sort="-timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(POLAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in POLAR_ENDPOINTS.items()
}
