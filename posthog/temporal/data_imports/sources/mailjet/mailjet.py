import base64
from datetime import date, datetime
from typing import Any, Optional

import requests

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.mailjet.settings import MAILJET_ENDPOINTS


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for Mailjet API filters."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = MAILJET_ENDPOINTS[name]

    params: dict[str, Any] = {
        "Limit": config.page_size,
    }

    if name == "message":
        params["ShowSubject"] = "true"

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "ID",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "Data",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def get_auth_header(api_key: str, api_secret: str) -> dict[str, str]:
    """Create Basic Auth header for Mailjet API"""
    credentials = f"{api_key}:{api_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded_credentials}"}


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Validate Mailjet API credentials by making a test request"""
    try:
        headers = get_auth_header(api_key, api_secret)
        response = requests.get(
            "https://api.mailjet.com/v3/REST/contactslist",
            headers=headers,
            params={"Limit": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def mailjet_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = MAILJET_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.mailjet.com/v3/REST",
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": api_secret,
            },
            "paginator": {
                "type": "offset",
                "limit": endpoint_config.page_size,
                "offset_param": "Offset",
                "limit_param": "Limit",
                "total_path": "Total",
            },
        },
        "resource_defaults": {
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "Limit": endpoint_config.page_size,
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
        primary_keys=["ID"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
