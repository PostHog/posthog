from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_source
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def extract_data_center(api_key: str) -> str:
    """Extract data center from Mailchimp API key.

    Mailchimp API keys are in format: <key>-<dc> where dc is the data center (e.g., us1, us19).
    """
    parts = api_key.split("-")
    if len(parts) != 2:
        raise ValueError("Invalid Mailchimp API key format. Expected format: <key>-<datacenter>")
    return parts[1]


def get_base_url(api_key: str) -> str:
    """Get the Mailchimp API base URL for the given API key."""
    dc = extract_data_center(api_key)
    return f"https://{dc}.api.mailchimp.com/3.0"


def validate_credentials(api_key: str) -> bool:
    """Validate Mailchimp API credentials by making a test request."""
    try:
        base_url = get_base_url(api_key)
        response = requests.get(
            f"{base_url}/ping",
            auth=("anystring", api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None = None,
) -> EndpointResource:
    """Get endpoint resource configuration for a given Mailchimp endpoint."""

    resources: dict[str, EndpointResource] = {
        "lists": {
            "name": "lists",
            "table_name": "lists",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "lists",
                "path": "/lists",
                "params": {
                    "count": 1000,
                    "offset": 0,
                    "sort_field": "date_created",
                    "sort_dir": "ASC",
                },
            },
            "table_format": "delta",
        },
        "campaigns": {
            "name": "campaigns",
            "table_name": "campaigns",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
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
                    "offset": 0,
                    "sort_field": "send_time",
                    "sort_dir": "ASC",
                    "status": "sent",
                },
            },
            "table_format": "delta",
        },
        "automations": {
            "name": "automations",
            "table_name": "automations",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "automations",
                "path": "/automations",
                "params": {
                    "count": 1000,
                    "offset": 0,
                },
            },
            "table_format": "delta",
        },
        "reports": {
            "name": "reports",
            "table_name": "reports",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
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
                    "offset": 0,
                },
            },
            "table_format": "delta",
        },
    }

    if name not in resources:
        raise ValueError(f"Unknown Mailchimp endpoint: {name}")

    return resources[name]


def mailchimp_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None = None,
    logger: FilteringBoundLogger | None = None,
):
    """Create a Mailchimp data source using the REST API pattern."""

    base_url = get_base_url(api_key)

    resource = get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {
                "type": "http_basic",
                "username": "anystring",
                "password": api_key,
            },
            "paginator": {
                "type": "offset",
                "limit": 1000,
                "offset": 0,
                "offset_param": "offset",
                "limit_param": "count",
                "total_path": "total_items",
            },
        },
        "resources": [resource],
    }

    yield from rest_api_source(
        config=config,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        name=f"mailchimp_{endpoint}",
    )
