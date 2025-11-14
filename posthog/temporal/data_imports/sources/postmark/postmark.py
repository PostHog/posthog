from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


class PostmarkOffsetPaginator(BasePaginator):
    """Custom paginator for Postmark API's offset-based pagination."""

    def __init__(self):
        super().__init__()
        self.offset = 0
        self.count = 500  # Postmark's max page size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        """Update the offset based on the response."""
        if data and len(data) == self.count:
            # If we got a full page, there might be more data
            self.offset += self.count
        else:
            # If we got less than a full page, we're done
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        """Add offset and count parameters to the request."""
        if request.params is None:
            request.params = {}
        request.params["offset"] = str(self.offset)
        request.params["count"] = str(self.count)


def get_resource(name: str, should_use_incremental_field: bool, server_token: str) -> EndpointResource:
    """Get the endpoint resource configuration for a given Postmark endpoint."""

    resources: dict[str, EndpointResource] = {
        "bounces": {
            "name": "bounces",
            "table_name": "bounces",
            "primary_key": "ID",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "Bounces",
                "path": "/bounces",
                "paginator": PostmarkOffsetPaginator(),
                "params": {
                    "BouncedAt": {
                        "type": "incremental",
                        "cursor_path": "BouncedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).isoformat() if not isinstance(x, datetime) else x,
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
            "primary_key": "MessageID",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "Messages",
                "path": "/messages/outbound",
                "paginator": PostmarkOffsetPaginator(),
                "params": {
                    "ReceivedAt": {
                        "type": "incremental",
                        "cursor_path": "ReceivedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).isoformat() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "message_streams": {
            "name": "message_streams",
            "table_name": "message_streams",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "MessageStreams",
                "path": "/message-streams",
            },
            "table_format": "delta",
        },
        "servers": {
            "name": "servers",
            "table_name": "servers",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "$",  # Response is the server object itself
                "path": "/server",
            },
            "table_format": "delta",
        },
        "domains": {
            "name": "domains",
            "table_name": "domains",
            "primary_key": "ID",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "Domains",
                "path": "/domains",
                "paginator": PostmarkOffsetPaginator(),
            },
            "table_format": "delta",
        },
        "deliverystats": {
            "name": "deliverystats",
            "table_name": "deliverystats",
            "primary_key": "Name",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "$",  # Response is an object with stats
                "path": "/deliverystats",
            },
            "table_format": "delta",
        },
    }

    return resources[name]


def validate_credentials(server_token: str) -> bool:
    """Validate Postmark API credentials by making a test request."""
    try:
        headers = {
            "X-Postmark-Server-Token": server_token,
            "Accept": "application/json",
        }
        response = requests.get("https://api.postmarkapp.com/server", headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def postmark_source(
    server_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[str],
    logger: FilteringBoundLogger,
):
    """Create a Postmark source for a given endpoint."""

    resource = get_resource(endpoint, should_use_incremental_field, server_token)

    config = RESTAPIConfig(
        client={"base_url": "https://api.postmarkapp.com", "headers": {"X-Postmark-Server-Token": server_token}},
        resources=[resource],
    )

    # Handle incremental sync
    if should_use_incremental_field and db_incremental_field_last_value:
        if endpoint in ["bounces", "messages"]:
            # Update the incremental cursor initial value
            if resource["endpoint"]["params"]:
                field_name = "BouncedAt" if endpoint == "bounces" else "ReceivedAt"
                if field_name in resource["endpoint"]["params"]:
                    resource["endpoint"]["params"][field_name]["initial_value"] = db_incremental_field_last_value

    yield from rest_api_resources(config)
