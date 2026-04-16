from dataclasses import dataclass


@dataclass
class WorkOSEndpointConfig:
    name: str
    path: str
    partition_key: str = "created_at"
    page_size: int = 100  # WorkOS default, max is 100


@dataclass
class WorkOSNestedEndpointConfig:
    """Configuration for nested endpoints that require a parent ID (N+1 pattern).

    For example, organization_memberships requires a user_id or organization_id.
    We iterate over the parent endpoint and fetch children for each parent.
    """

    name: str
    path: str  # Path template, e.g., "/user_management/organization_memberships"
    parent_endpoint: str  # Name of the parent endpoint, e.g., "users"
    parent_id_field: str  # Field name on parent object to get ID, e.g., "id"
    parent_param: str  # Query parameter name for parent ID, e.g., "user_id"
    partition_key: str = "created_at"
    limit: int = 100  # WorkOS default, max is 100


# WorkOS API does not support filtering by updated_at, so only full refresh is supported.
WORKOS_ENDPOINTS: dict[str, WorkOSEndpointConfig] = {
    "users": WorkOSEndpointConfig(name="users", path="/user_management/users"),
    "organizations": WorkOSEndpointConfig(name="organizations", path="/organizations"),
    "invitations": WorkOSEndpointConfig(name="invitations", path="/user_management/invitations"),
    "resources": WorkOSEndpointConfig(name="resources", path="/authorization/resources"),
}

WORKOS_NESTED_ENDPOINTS: dict[str, WorkOSNestedEndpointConfig] = {
    "organization_memberships": WorkOSNestedEndpointConfig(
        name="organization_memberships",
        path="/user_management/organization_memberships",
        parent_endpoint="users",
        parent_id_field="id",
        parent_param="user_id",
    ),
}

# All endpoints (top-level + nested)
ENDPOINTS = tuple(list(WORKOS_ENDPOINTS.keys()) + list(WORKOS_NESTED_ENDPOINTS.keys()))
