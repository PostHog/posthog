from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ClerkEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str = "updated_at"
    partition_key: Optional[str] = None
    page_size: int = 100  # Clerk default, max is 500
    # Some Clerk endpoints return {data: [...], total_count: ...}, others return direct arrays
    is_wrapped_response: bool = False


CLERK_ENDPOINTS: dict[str, ClerkEndpointConfig] = {
    "users": ClerkEndpointConfig(
        name="users",
        path="/users",
        default_incremental_field="updated_at",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.Integer,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.Integer,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "last_sign_in_at",
                "type": IncrementalFieldType.Integer,
                "field": "last_sign_in_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "last_active_at",
                "type": IncrementalFieldType.Integer,
                "field": "last_active_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "organizations": ClerkEndpointConfig(
        name="organizations",
        path="/organizations",
        default_incremental_field="updated_at",
        partition_key="created_at",
        is_wrapped_response=True,
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.Integer,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.Integer,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "last_active_at",
                "type": IncrementalFieldType.Integer,
                "field": "last_active_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "organization_memberships": ClerkEndpointConfig(
        name="organization_memberships",
        path="/organization_memberships",
        default_incremental_field="updated_at",
        partition_key="created_at",
        is_wrapped_response=True,
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.Integer,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.Integer,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "invitations": ClerkEndpointConfig(
        name="invitations",
        path="/invitations",
        default_incremental_field="updated_at",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.Integer,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.Integer,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(CLERK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLERK_ENDPOINTS.items()
}
