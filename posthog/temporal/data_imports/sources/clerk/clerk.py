from typing import Any

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.clerk.settings import CLERK_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource


def get_resource(name: str) -> EndpointResource:
    config = CLERK_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
    }

    # Only set data_selector for endpoints that return wrapped responses {data: [...], total_count: ...}
    if config.is_wrapped_response:
        endpoint_config["data_selector"] = "data"

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


class ClerkPaginator(BasePaginator):
    """Paginator for Clerk API using offset-based pagination."""

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self._limit = limit
        self._offset = 0

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Clerk endpoints return either:
        # - Direct array: /users, /invitations
        # - Wrapped object {data: [...], total_count: ...}: /organizations, /organization_memberships
        if isinstance(res, dict) and "data" in res:
            items = res["data"]
        elif isinstance(res, list):
            items = res
        else:
            items = []

        # If we got fewer items than the limit, we've reached the end
        if len(items) < self._limit:
            self._has_next_page = False
        else:
            self._offset += len(items)
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset


# Timestamp fields that need conversion from milliseconds to seconds
TIMESTAMP_FIELDS = [
    "created_at",
    "updated_at",
    "last_sign_in_at",
    "last_active_at",
    "mfa_enabled_at",
    "mfa_disabled_at",
    "password_last_updated_at",
    "legal_accepted_at",
    "expires_at",  # invitations
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Clerk timestamp fields from milliseconds to seconds."""
    for field in TIMESTAMP_FIELDS:
        if field in item and item[field] is not None:
            # Clerk returns timestamps in milliseconds, convert to seconds
            # Use integer division to maintain int64 type for delta table compatibility
            item[field] = item[field] // 1000
    return item


def validate_credentials(secret_key: str) -> tuple[bool, str | None]:
    """Validate Clerk API credentials by making a test request."""
    url = "https://api.clerk.com/v1/users"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        try:
            error_data = response.json()
            if error_data.get("errors"):
                return False, error_data["errors"][0].get("message", response.text)
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def clerk_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = CLERK_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.clerk.com/v1",
            "auth": {
                "type": "bearer",
                "token": secret_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": ClerkPaginator(limit=endpoint_config.page_size),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "limit": endpoint_config.page_size,
                },
            },
        },
        "resources": [get_resource(endpoint)],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0].add_map(_convert_timestamps)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
    )
