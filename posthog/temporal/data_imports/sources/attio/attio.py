from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


class AttioJSONBodyPaginator(BasePaginator):
    """Paginator for Attio POST endpoints that require pagination in the JSON body."""

    def __init__(self, limit: int = 100):
        super().__init__()
        self._limit = limit
        self._offset = 0
        self._has_next_page = True

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            response_data = response.json()
            returned_data = response_data.get("data", [])

            if len(returned_data) < self._limit:
                self._has_next_page = False
            else:
                self._has_next_page = True
                self._offset += self._limit
        except Exception:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}

        request.json["offset"] = self._offset
        request.json["limit"] = self._limit


class AttioOffsetPaginator(BasePaginator):
    """Paginator for Attio GET endpoints using offset-based pagination."""

    def __init__(self, limit: int = 100):
        super().__init__()
        self._limit = limit
        self._offset = 0
        self._has_next_page = True

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            response_data = response.json()
            returned_data = response_data.get("data", [])

            if len(returned_data) < self._limit:
                self._has_next_page = False
            else:
                self._has_next_page = True
                self._offset += self._limit
        except Exception:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["offset"] = self._offset
        request.params["limit"] = self._limit


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    if "id" in item and isinstance(item["id"], dict):
        id_obj = item.pop("id")
        for key, value in id_obj.items():
            item[key] = value
    return item


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    """Build an EndpointResource from the endpoint configuration."""
    config = ATTIO_ENDPOINTS[name]

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "data_selector": "data",
    }

    if config.method == "POST":
        endpoint_config["method"] = "POST"
        endpoint_config["json"] = {"sorts": [{"attribute": "created_at", "direction": "asc"}]}
        endpoint_config["paginator"] = AttioJSONBodyPaginator(limit=config.page_size)
    else:
        endpoint_config["paginator"] = AttioOffsetPaginator(limit=config.page_size)

    return {
        "name": config.name,
        "table_name": config.name,
        **({"primary_key": config.primary_key} if should_use_incremental_field else {}),
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> bool:
    """Validate Attio API credentials by making a test request."""
    try:
        res = requests.get(
            "https://api.attio.com/v2/self",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        return res.status_code == 200
    except Exception:
        return False


def attio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    """Main source function for Attio data import."""
    endpoint_config = ATTIO_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.attio.com",
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        },
        "resource_defaults": {
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1
    resource = resources[0].add_map(_flatten_item)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )
