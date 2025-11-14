import base64
from typing import Any

import dlt
import requests

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "contactslist": {
            "name": "contactslist",
            "table_name": "contactslist",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Data",
                "path": "/contactslist",
                "params": {
                    "Limit": 100,
                },
            },
            "table_format": "delta",
        },
        "contacts": {
            "name": "contacts",
            "table_name": "contacts",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Data",
                "path": "/contact",
                "params": {
                    "Limit": 100,
                },
            },
            "table_format": "delta",
        },
        "campaign": {
            "name": "campaign",
            "table_name": "campaign",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Data",
                "path": "/campaign",
            },
            "table_format": "delta",
        },
        "message": {
            "name": "message",
            "table_name": "message",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Data",
                "path": "/message",
                "params": {
                    "ShowSubject": "true",
                    "Limit": 100,
                },
            },
            "table_format": "delta",
        },
        "listrecipient": {
            "name": "listrecipient",
            "table_name": "listrecipient",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Data",
                "path": "/listrecipient",
                "params": {
                    "Limit": 100,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


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


@dlt.source(max_table_nesting=0)
def mailjet_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> Any:
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
                "limit": 100,
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
                    "Limit": 100,
                },
            },
        },
        "resources": [get_resource(endpoint, False)],
    }

    yield from rest_api_resources(config)
