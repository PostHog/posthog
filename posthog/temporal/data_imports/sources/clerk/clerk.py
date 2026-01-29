from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.clerk.settings import CLERK_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = CLERK_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    # Clerk uses offset-based pagination, so we don't add incremental filters to params
    # The incremental sync is handled by the DLT incremental object

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": params,
        },
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

        # Clerk returns data in a 'data' array
        items = res.get("data", [])

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


def validate_credentials(secret_key: str) -> bool:
    """Validate Clerk API credentials by making a test request."""
    url = "https://api.clerk.com/v1/users"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def clerk_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
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
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
