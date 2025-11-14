import base64
from typing import Any

import dlt
import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    """
    Get the endpoint resource configuration for Customer.io endpoints.

    Customer.io uses the App API for reporting and data retrieval.
    Authentication is done using App API Key via Basic Auth.
    """
    resources: dict[str, EndpointResource] = {
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
                "path": "/v1/campaigns",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "updated",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "newsletters": {
            "name": "newsletters",
            "table_name": "newsletters",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "newsletters",
                "path": "/v1/newsletters",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "updated",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "messages": {
            "name": "messages",
            "table_name": "messages",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "messages",
                "path": "/v1/messages",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "created_at",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "actions": {
            "name": "actions",
            "table_name": "actions",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "actions",
                "path": "/v1/actions",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "updated",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "segments": {
            "name": "segments",
            "table_name": "segments",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "segments",
                "path": "/v1/segments",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "updated",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "broadcasts": {
            "name": "broadcasts",
            "table_name": "broadcasts",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "broadcasts",
                "path": "/v1/broadcasts",
                "params": {
                    "start": {
                        "type": "incremental",
                        "cursor_path": "updated",
                        "initial_value": 0,  # type: ignore
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class CustomerIOPaginator(BasePaginator):
    """
    Customer.io uses cursor-based pagination with 'next' cursor in response.
    """

    def __init__(self):
        super().__init__()
        self.next_cursor: str | None = None

    def update_state(self, response: Response) -> None:
        """Extract next cursor from response."""
        data = response.json()
        # Customer.io returns pagination info in 'next' field
        self.next_cursor = data.get("next")

    def update_request(self, request: Request) -> None:
        """Add cursor to request params if available."""
        if self.next_cursor:
            if request.params is None:
                request.params = {}
            request.params["start"] = self.next_cursor

    @property
    def has_next_page(self) -> bool:
        """Check if there are more pages."""
        return self.next_cursor is not None


def validate_credentials(app_api_key: str, region: str = "US") -> bool:
    """
    Validate Customer.io App API credentials by making a test request.

    Args:
        app_api_key: Customer.io App API Key (used as username in Basic Auth, password is empty)
        region: Region (US or EU)

    Returns:
        True if credentials are valid, False otherwise
    """
    base_url = "https://api.customer.io/v1" if region == "US" else "https://api-eu.customer.io/v1"

    # Encode API key as username with empty password for Basic Auth
    credentials = base64.b64encode(f"{app_api_key}:".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}

    try:
        # Try to fetch campaigns as a test
        response = requests.get(f"{base_url}/campaigns", headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@dlt.source(max_table_nesting=0)
def customer_io_source(
    app_api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None = None,
):
    """
    DLT source for Customer.io data.

    Args:
        app_api_key: Customer.io App API Key
        region: Region (US or EU)
        endpoint: The endpoint to fetch data from
        team_id: PostHog team ID
        job_id: PostHog job ID
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last synced value for incremental field
    """
    base_url = "https://api.customer.io" if region == "US" else "https://api-eu.customer.io"

    # Encode API key as username with empty password for Basic Auth
    credentials = base64.b64encode(f"{app_api_key}:".encode()).decode()

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {
                "type": "http_basic",
                "username": app_api_key,
                "password": "",
            },
            "headers": {
                "Authorization": f"Basic {credentials}",
            },
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "params": {
                    "limit": 100,
                },
            },
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    # Update initial value if we have a last synced value
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        resource = config["resources"][0]
        if "params" in resource["endpoint"] and resource["endpoint"]["params"]:
            start_param = resource["endpoint"]["params"].get("start")
            if start_param and isinstance(start_param, dict):
                start_param["initial_value"] = db_incremental_field_last_value

    yield from rest_api_resources(config, CustomerIOPaginator())
