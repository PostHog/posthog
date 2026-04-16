from collections.abc import Iterator
from datetime import datetime
from typing import Any

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.workos.settings import (
    WORKOS_ENDPOINTS,
    WORKOS_NESTED_ENDPOINTS,
    WorkOSNestedEndpointConfig,
)


def get_resource(name: str) -> EndpointResource:
    config = WORKOS_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
    }

    # All WorkOS endpoints return wrapped responses {data: [...], list_metadata: ...}
    endpoint_config["data_selector"] = "data"

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


class WorkOSPaginator(BasePaginator):
    """Paginator for WorkOS API using cursor-based pagination."""

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self._limit = limit
        self.after = ""  # null or string from list_metadata.after

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # WorkOS endpoints return wrapped responses, extract pagination metadata
        if isinstance(res, dict) and "data" in res:
            list_metadata = res.get("list_metadata", {})
            if not list_metadata.get("after"):
                self._has_next_page = False
            else:
                self.after = list_metadata["after"]
                self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            if request.params is None:
                request.params = {}
            request.params["after"] = self.after


# Timestamp fields that need conversion from ISO 8601 strings to Unix timestamps (seconds)
TIMESTAMP_FIELDS = [
    "created_at",
    "updated_at",
    "last_sign_in_at",  # users
    "expires_at",  # invitations
    "revoked_at",  # invitations
    "accepted_at",  # invitations
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Workos timestamp fields from ISO 8601 to seconds."""
    for field in TIMESTAMP_FIELDS:
        if field in item and item[field] is not None:
            # WorkOS returns ISO 8601 strings like "2026-03-23T01:26:25.590Z"
            dt = datetime.fromisoformat(item[field].replace("Z", "+00:00"))
            item[field] = int(dt.timestamp())

    return item


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Workos API credentials by making a test request."""
    url = "https://api.workos.com/user_management/users"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        try:
            error_data = response.json()
            if error_data.get("message"):
                return False, error_data["message"]
            elif error_data.get("errors"):
                return False, error_data["errors"][0].get("message", response.text)
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _fetch_all_pages(api_key: str, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Fetch all pages from a WorkOS endpoint using cursor-based pagination."""
    url = f"https://api.workos.com{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    request_params = {"limit": 100, **(params or {})}
    cursor: str | None = None

    while True:
        if cursor:
            request_params["after"] = cursor
        response = requests.get(url, headers=headers, params=request_params, timeout=30)
        response.raise_for_status()

        data = response.json()
        items = data.get("data", [])

        yield from items

        # Check for next page
        list_metadata = data.get("list_metadata", {})
        cursor = list_metadata.get("after")

        if not cursor:
            break


def _get_nested_resource_iterator(
    api_key: str,
    nested_config: WorkOSNestedEndpointConfig,
) -> Iterator[dict[str, Any]]:
    """Iterate over parent resources and fetch nested children for each (N+1 pattern).

    For example, for organization_memberships:
    1. Fetch all users (parent)
    2. For each user, fetch all organization_memberships with user_id=<user.id>
    3. Attach user_id to each membership record for joining in the data warehouse
    """
    parent_config = WORKOS_ENDPOINTS[nested_config.parent_endpoint]

    # Step 1: Fetch all parent resources
    for parent in _fetch_all_pages(api_key, parent_config.path):
        parent_id = parent[nested_config.parent_id_field]

        # Step 2: Fetch all children for this parent
        child_params = {nested_config.parent_param: parent_id}

        for child in _fetch_all_pages(api_key, nested_config.path, child_params):
            # Step 3: Attach parent ID to child record for warehouse joins
            child[nested_config.parent_param] = parent_id
            yield _convert_timestamps(child)


def workos_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    # Check if this is a nested endpoint (N+1 pattern)
    if endpoint in WORKOS_NESTED_ENDPOINTS:
        nested_config = WORKOS_NESTED_ENDPOINTS[endpoint]

        return SourceResponse(
            name=endpoint,
            items=lambda nc=nested_config: _get_nested_resource_iterator(api_key, nc),
            # Composite primary key includes parent ID for uniqueness
            primary_keys=[nested_config.parent_param, "id"],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=[nested_config.partition_key],
        )

    # Standard top-level endpoint
    endpoint_config = WORKOS_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.workos.com",
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": WorkOSPaginator(limit=endpoint_config.page_size),
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
