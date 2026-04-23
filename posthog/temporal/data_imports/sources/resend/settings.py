from dataclasses import dataclass, field
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ResendEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    # Cursor-paginated endpoints (e.g. /emails) use `limit` + `after`. Flat endpoints
    # return the full list in a single response, so page_size is None.
    page_size: Optional[int] = None
    # For fan-out endpoints like `contacts`, names the parent endpoint we iterate to
    # resolve the path parameter.
    parent: Optional[str] = None


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


RESEND_ENDPOINTS: dict[str, ResendEndpointConfig] = {
    "audiences": ResendEndpointConfig(
        name="audiences",
        path="/audiences",
        partition_key="created_at",
        default_incremental_field="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "broadcasts": ResendEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        partition_key="created_at",
        default_incremental_field="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "domains": ResendEndpointConfig(
        name="domains",
        path="/domains",
        partition_key="created_at",
        default_incremental_field="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "emails": ResendEndpointConfig(
        name="emails",
        path="/emails",
        partition_key="created_at",
        default_incremental_field="created_at",
        page_size=100,
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "contacts": ResendEndpointConfig(
        name="contacts",
        path="/audiences/{audience_id}/contacts",
        partition_key="created_at",
        default_incremental_field="created_at",
        parent="audiences",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
}


ENDPOINTS = tuple(RESEND_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RESEND_ENDPOINTS.items()
}
