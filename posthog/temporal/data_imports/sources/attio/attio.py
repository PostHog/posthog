from datetime import date, datetime
from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO 8601 string for Attio API filters.

    Attio only accepts timestamps with 'Z' suffix for UTC, not '+00:00'.
    """
    if isinstance(value, datetime):
        # Attio expects UTC with Z suffix (not +00:00)
        iso_str = value.isoformat()
        # Replace +00:00 with Z for UTC timezone
        if iso_str.endswith("+00:00"):
            iso_str = iso_str[:-6] + "Z"
        elif not iso_str.endswith("Z") and "+" not in iso_str:
            iso_str += "Z"
        return iso_str
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat() + "Z"
    # Assume string is already in correct format
    str_value = str(value)
    # Replace +00:00 with Z
    if str_value.endswith("+00:00"):
        str_value = str_value[:-6] + "Z"
    elif str_value and not str_value.endswith("Z") and "+" not in str_value and "T" in str_value:
        str_value += "Z"
    return str_value


class AttioJSONBodyPaginator(BasePaginator):
    """Paginator for Attio POST endpoints that require pagination in the JSON body."""

    def __init__(self, limit: int = 100, initial_json: Optional[dict[str, Any]] = None):
        super().__init__()
        self._limit = limit
        self._current_offset = 0
        self._next_offset: Optional[int] = 0
        self._has_next_page = False
        self._initial_json = initial_json or {}

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
        # Ensure we preserve the initial json (filter, sorts) on every request
        if request.json is None:
            request.json = dict(self._initial_json)
        else:
            # Merge initial json with any existing properties
            for key, value in self._initial_json.items():
                if key not in request.json:
                    request.json[key] = value

        if self._next_offset is not None:
            self._current_offset = self._next_offset

        request.json["offset"] = self._current_offset
        request.json["limit"] = self._limit


class AttioOffsetPaginator(BasePaginator):
    """Paginator for Attio GET endpoints using offset-based pagination."""

    def __init__(self, limit: int = 100):
        super().__init__()
        self._limit = limit
        self._current_offset = 0
        self._next_offset: Optional[int] = 0
        self._has_next_page = False

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
        if request.params is None:
            request.params = {}

        if self._next_offset is not None:
            self._current_offset = self._next_offset

        request.params["offset"] = self._current_offset
        request.params["limit"] = self._limit


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    if "id" in item and isinstance(item["id"], dict):
        id_obj = item.pop("id")
        for key, value in id_obj.items():
            item[key] = value
    return item


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    """Build an EndpointResource from the endpoint configuration."""
    config = ATTIO_ENDPOINTS[name]

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "data_selector": "data",
    }

    # Build filter for incremental syncs
    # Attio timestamp filters require nested "value" property
    incremental_filter: dict[str, Any] | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filter_field = incremental_field or config.default_incremental_field
        formatted_value = _format_incremental_value(db_incremental_field_last_value)
        incremental_filter = {filter_field: {"value": {"$gt": formatted_value}}}

    if config.method == "POST":
        endpoint_config["method"] = "POST"
        json_body: dict[str, Any] = {"sorts": [{"attribute": "created_at", "direction": "asc"}]}
        if incremental_filter:
            json_body["filter"] = incremental_filter
        endpoint_config["json"] = json_body
        # Pass the json body to paginator so it can preserve it on each request
        endpoint_config["paginator"] = AttioJSONBodyPaginator(limit=config.page_size, initial_json=json_body)
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
    incremental_field: str | None = None,
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
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
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
