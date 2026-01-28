from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


class AttioJSONBodyPaginator(BasePaginator):
    """
    Custom paginator for Attio POST endpoints that require pagination in the JSON body.

    Attio POST endpoints (like /v2/objects/{object}/records/query) expect offset and limit
    in the request body, not as query parameters.
    """

    def __init__(self, limit: int = 100):
        super().__init__()
        self._limit = limit
        self._offset = 0
        self._has_next_page = True

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        """Update pagination state based on response data."""
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
        """Update the request JSON body with pagination parameters."""
        if request.json is None:
            request.json = {}

        request.json["offset"] = self._offset
        request.json["limit"] = self._limit


class AttioOffsetPaginator(BasePaginator):
    """
    Custom paginator for Attio GET endpoints.

    Attio's API doesn't return a 'total' field, so we determine if there are more pages
    by checking if the returned data count equals the limit.
    """

    def __init__(self, limit: int = 100):
        super().__init__()
        self._limit = limit
        self._offset = 0
        self._has_next_page = True

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        """Update pagination state based on response data."""
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
        """Update the request query params with pagination parameters."""
        if request.params is None:
            request.params = {}

        request.params["offset"] = self._offset
        request.params["limit"] = self._limit


def _get_id_field_for_endpoint(endpoint: str) -> str:
    """Get the nested ID field name for a given endpoint."""
    id_field_map = {
        "companies": "record_id",
        "people": "record_id",
        "deals": "record_id",
        "users": "record_id",
        "workspaces": "record_id",
        "lists": "list_id",
        "notes": "note_id",
        "tasks": "task_id",
        "workspace_members": "workspace_member_id",
    }
    return id_field_map.get(endpoint, "record_id")


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    if "id" in item and isinstance(item["id"], dict):
        id_obj = item.pop("id")
        # Merge all id fields into the root
        for key, value in id_obj.items():
            item[key] = value
    return item


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    """
    Define endpoint resources for Attio API.

    Attio API structure:
    - Objects (companies, people, deals, users, workspaces) use /v2/objects/{object}/records/query (POST)
    - Lists use /v2/lists (GET)
    - Notes use /v2/notes (GET)
    - Tasks use /v2/tasks (GET)
    - Workspace members use /v2/workspace_members (GET)
    """

    # Common configuration for object records (companies, people, deals, users, workspaces)
    # These all use a POST request to query records with filtering and sorting
    object_endpoints = {
        "companies": "companies",
        "people": "people",
        "deals": "deals",
        "users": "users",
        "workspaces": "workspaces",
    }

    if name in object_endpoints:
        return {
            "name": name,
            "table_name": name,
            **({"primary_key": "record_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": f"/v2/objects/{object_endpoints[name]}/records/query",
                "method": "POST",
                "data_selector": "data",
                "json": {
                    "sorts": [{"attribute": "created_at", "direction": "asc"}],
                },
                "paginator": AttioJSONBodyPaginator(limit=100),
            },
            "table_format": "delta",
        }

    # Lists endpoint
    if name == "lists":
        return {
            "name": "lists",
            "table_name": "lists",
            **({"primary_key": "list_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/lists",
                "data_selector": "data",
                "paginator": AttioOffsetPaginator(limit=100),
            },
            "table_format": "delta",
        }

    # Notes endpoint
    if name == "notes":
        return {
            "name": "notes",
            "table_name": "notes",
            **({"primary_key": "note_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/notes",
                "data_selector": "data",
                "paginator": AttioOffsetPaginator(limit=100),
            },
            "table_format": "delta",
        }

    # Tasks endpoint
    if name == "tasks":
        return {
            "name": "tasks",
            "table_name": "tasks",
            **({"primary_key": "task_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/tasks",
                "data_selector": "data",
                "paginator": AttioOffsetPaginator(limit=100),
            },
            "table_format": "delta",
        }

    # Workspace members endpoint
    if name == "workspace_members":
        return {
            "name": "workspace_members",
            "table_name": "workspace_members",
            **({"primary_key": "workspace_member_id"} if should_use_incremental_field else {}),
            "write_disposition": "replace",  # Workspace members don't have incremental support
            "endpoint": {
                "path": "/v2/workspace_members",
                "data_selector": "data",
                "paginator": AttioOffsetPaginator(limit=100),
            },
            "table_format": "delta",
        }

    raise ValueError(f"Unknown Attio endpoint: {name}")


def attio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    """
    Main source function for Attio data import.

    Args:
        api_key: Attio API key
        endpoint: Name of the endpoint to sync (e.g., "companies", "people", etc.)
        team_id: PostHog team ID
        job_id: Job ID for this import
        logger: Logger instance
        db_incremental_field_last_value: Last value of the incremental field from previous sync
        should_use_incremental_field: Whether to use incremental syncing
    """

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

    dlt_resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    # Flatten the nested ID structure into the root level
    resource = dlt_resources[0].add_map(_flatten_item)
    yield from resource


def validate_credentials(api_key: str) -> bool:
    """
    Validate Attio API credentials by making a test request.

    Args:
        api_key: Attio API key

    Returns:
        True if credentials are valid, False otherwise
    """
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
