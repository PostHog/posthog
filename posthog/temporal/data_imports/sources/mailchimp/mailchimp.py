from typing import Any

import dlt
import requests
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


class MailchimpPaginator(BasePaginator):
    """Custom paginator for Mailchimp API using offset-based pagination."""

    def __init__(self) -> None:
        super().__init__()
        self.offset = 0
        self.count = 0

    def update_state(self, response: requests.Response) -> None:
        """Update paginator state from response."""
        data = response.json()
        total_items = data.get("total_items", 0)
        self.count = len(data.get(self._get_data_key(response.url), []))
        self.offset += self.count

        if self.offset >= total_items or self.count == 0:
            self._has_next_page = False
        else:
            self._has_next_page = True

    def update_request(self, request: dict[str, Any]) -> None:
        """Update request with pagination parameters."""
        if request.get("params") is None:
            request["params"] = {}
        request["params"]["offset"] = self.offset
        request["params"]["count"] = 1000  # Mailchimp max is 1000

    def _get_data_key(self, url: str) -> str:
        """Get the data key from the URL path."""
        if "lists" in url and "members" not in url:
            return "lists"
        elif "campaigns" in url:
            return "campaigns"
        elif "automations" in url:
            return "automations"
        elif "reports" in url:
            return "reports"
        return "data"


def get_resource(name: str, api_key: str, server_prefix: str, should_use_incremental_field: bool) -> EndpointResource:
    """Get endpoint resource configuration for Mailchimp API."""
    resources: dict[str, EndpointResource] = {
        "lists": {
            "name": "lists",
            "table_name": "lists",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "lists",
                "path": "/lists",
                "params": {
                    "count": 1000,
                },
            },
        },
        "campaigns": {
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "campaigns",
                "path": "/campaigns",
                "params": {
                    "count": 1000,
                    "since_send_time": {
                        "type": "incremental",
                        "cursor_path": "send_time",
                        "initial_value": "1970-01-01T00:00:00+00:00",
                    }
                    if should_use_incremental_field
                    else None,
                    "sort_field": "send_time",
                    "sort_dir": "ASC",
                },
            },
            "table_format": "delta",
        },
        "automations": {
            "name": "automations",
            "table_name": "automations",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "automations",
                "path": "/automations",
                "params": {
                    "count": 1000,
                },
            },
        },
        "reports": {
            "name": "reports",
            "table_name": "reports",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "reports",
                "path": "/reports",
                "params": {
                    "count": 1000,
                    "since_send_time": {
                        "type": "incremental",
                        "cursor_path": "send_time",
                        "initial_value": "1970-01-01T00:00:00+00:00",
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


def validate_credentials(api_key: str) -> tuple[bool, str]:
    """Validate Mailchimp API credentials and extract server prefix.

    Returns:
        A tuple of (is_valid, server_prefix).
        If invalid, server_prefix will contain an error message.
    """
    # Extract server prefix from API key (last part after the dash)
    # API keys are in format: {key}-{server_prefix}
    if "-" not in api_key:
        return False, "Invalid API key format. API key should contain a server prefix (e.g., key-us1)"

    parts = api_key.split("-")
    if len(parts) < 2:
        return False, "Invalid API key format. API key should contain a server prefix (e.g., key-us1)"

    server_prefix = parts[-1]
    base_url = f"https://{server_prefix}.api.mailchimp.com/3.0"

    # Test the API key by making a simple request to the ping endpoint
    try:
        response = requests.get(
            f"{base_url}/ping",
            auth=("anystring", api_key),
            timeout=10,
        )

        if response.status_code == 200:
            return True, server_prefix
        elif response.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"API error: {response.status_code}"
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {str(e)}"


@dlt.source(max_table_nesting=0)
def mailchimp_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
):
    """Create a DLT source for Mailchimp data.

    Args:
        api_key: Mailchimp API key
        endpoint: The endpoint to sync (lists, campaigns, automations, reports)
        team_id: PostHog team ID
        job_id: PostHog job ID
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last value for incremental field
    """
    # Extract server prefix from API key
    is_valid, result = validate_credentials(api_key)
    if not is_valid:
        raise ValueError(f"Invalid Mailchimp credentials: {result}")

    server_prefix = result
    base_url = f"https://{server_prefix}.api.mailchimp.com/3.0"

    # Get resource configuration
    resource = get_resource(endpoint, api_key, server_prefix, should_use_incremental_field)

    # Configure REST API
    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {
                "type": "http_basic",
                "username": "anystring",  # Mailchimp accepts any string as username
                "password": api_key,
            },
            "paginator": MailchimpPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
        },
        "resources": [resource],
    }

    yield from rest_api_resources(config)
