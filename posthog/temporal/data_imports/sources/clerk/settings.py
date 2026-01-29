from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField


@dataclass
class ClerkEndpointConfig:
    name: str
    path: str
    partition_key: Optional[str] = None
    page_size: int = 100  # Clerk default, max is 500
    # Some Clerk endpoints return {data: [...], total_count: ...}, others return direct arrays
    is_wrapped_response: bool = False


# Note: Clerk API does not support filtering by updated_at, only created_at and last_active_at.
# Since we can't properly track record updates, we disable incremental sync and only support full refresh.
CLERK_ENDPOINTS: dict[str, ClerkEndpointConfig] = {
    "users": ClerkEndpointConfig(
        name="users",
        path="/users",
        partition_key="created_at",
    ),
    "organizations": ClerkEndpointConfig(
        name="organizations",
        path="/organizations",
        partition_key="created_at",
        is_wrapped_response=True,
    ),
    "organization_memberships": ClerkEndpointConfig(
        name="organization_memberships",
        path="/organization_memberships",
        partition_key="created_at",
        is_wrapped_response=True,
    ),
    "invitations": ClerkEndpointConfig(
        name="invitations",
        path="/invitations",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(CLERK_ENDPOINTS.keys())

# Incremental sync is disabled for Clerk - always empty
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CLERK_ENDPOINTS}
