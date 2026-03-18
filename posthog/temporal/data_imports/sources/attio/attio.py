from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource


class AttioOffsetPaginator(BasePaginator):
    """Paginator for Attio endpoints using offset-based pagination.

    Supports both POST endpoints (pagination in JSON body) and GET endpoints (pagination in query params).
    """

    def __init__(self, limit: int = 100, use_json_body: bool = False, initial_json: Optional[dict[str, Any]] = None):
        super().__init__()
        self._limit = limit
        self._current_offset = 0
        self._next_offset: Optional[int] = 0
        self._has_next_page = False
        self._use_json_body = use_json_body
        self._initial_json = initial_json or {}

    def init_request(self, request: Request) -> None:
        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            response_data = response.json()
            returned_data = response_data.get("data", [])

            if len(returned_data) < self._limit:
                self._has_next_page = False
                self._next_offset = None
            else:
                self._has_next_page = True
                self._next_offset = self._current_offset + self._limit
        except Exception:
            self._has_next_page = False
            self._next_offset = None

    def update_request(self, request: Request) -> None:
        if self._next_offset is not None:
            self._current_offset = self._next_offset

        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    if "id" in item and isinstance(item["id"], dict):
        id_obj = item.pop("id")
        for key, value in id_obj.items():
            item[key] = value
    return item


def get_resource(name: str) -> EndpointResource:
    """Build an EndpointResource from the endpoint configuration.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    """
    config = ATTIO_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
    }

    if config.method == "POST":
        endpoint_config["method"] = "POST"
        json_body: dict[str, Any] = {"sorts": [{"attribute": "created_at", "direction": "asc"}]}
        endpoint_config["json"] = json_body
        endpoint_config["paginator"] = AttioOffsetPaginator(
            limit=config.page_size, use_json_body=True, initial_json=json_body
        )
    else:
        endpoint_config["paginator"] = AttioOffsetPaginator(limit=config.page_size)

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
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
        if res.status_code == 200:
            return True, None

        try:
            error_data = res.json()
            if error_data.get("code") == "missing_value":
                return False, "Invalid Attio API key"
        except Exception:
            pass
        return False, f"HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return False, str(e)


def attio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Main source function for Attio data import.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    The incremental parameters are kept for interface compatibility but are not used.
    """
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
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0].add_map(_flatten_item)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
        sort_mode="asc",
    )
