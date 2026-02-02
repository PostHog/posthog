from typing import Any

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.customer_io.settings import CUSTOMERIO_ENDPOINTS


def get_base_url(region: str) -> str:
    """Get the base URL for the Customer.io App API based on region."""
    if region == "EU":
        return "https://api-eu.customer.io/v1"
    return "https://api.customer.io/v1"


def get_resource(name: str) -> EndpointResource:
    config = CUSTOMERIO_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


class CustomerIOPaginator(BasePaginator):
    """Paginator for Customer.io API using cursor-based pagination."""

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self._limit = limit
        self._next_cursor: str | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Customer.io uses cursor-based pagination with a "next" field
        self._next_cursor = res.get("next")
        self._has_next_page = self._next_cursor is not None

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._next_cursor:
            if request.params is None:
                request.params = {}
            request.params["start"] = self._next_cursor


# Timestamp fields that need conversion from milliseconds to seconds
TIMESTAMP_FIELDS = [
    "created",
    "updated",
    "created_at",
    "updated_at",
    "last_activity_at",
    "sent_at",
    "opened_at",
    "clicked_at",
    "converted_at",
    "unsubscribed_at",
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Customer.io timestamp fields from milliseconds to seconds if needed."""
    for field in TIMESTAMP_FIELDS:
        if field in item and item[field] is not None:
            # Customer.io returns timestamps in seconds (Unix timestamp)
            # but some fields may be in milliseconds - normalize to seconds
            value = item[field]
            if isinstance(value, int) and value > 10000000000:
                # Likely milliseconds, convert to seconds
                item[field] = value // 1000
    return item


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    """Validate Customer.io API credentials by making a test request."""
    url = f"{get_base_url(region)}/segments"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10, allow_redirects=False)

        if response.status_code == 200:
            return True, None

        if response.status_code in (301, 302, 307, 308):
            other_region = "EU" if region == "US" else "US"
            return False, f"Wrong region selected. Please select {other_region} instead."

        if response.status_code == 401:
            return False, "Invalid API key. Make sure you're using an App API key (not a Track API key)."

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def customerio_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = CUSTOMERIO_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(region),
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": CustomerIOPaginator(limit=endpoint_config.page_size),
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
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
