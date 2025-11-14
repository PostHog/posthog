from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    """
    Define endpoint resources for Attio API.

    Attio API structure:
    - Objects (companies, people, deals, users, workspaces) use /v2/objects/{object}/records/query (POST)
    - Lists use /v2/lists (GET)
    - List entries use /v2/lists/{list_id}/entries (POST to query)
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
            **({"primary_key": "id.record_id"} if should_use_incremental_field else {}),
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
                    "limit": 100,
                    "sorts": [{"attribute": "created_at", "direction": "asc"}]
                    if should_use_incremental_field
                    else [],
                    "filter": {
                        "created_at": {
                            "type": "incremental",
                            "cursor_path": "created_at",
                            "initial_value": "1970-01-01T00:00:00Z",
                        }
                    }
                    if should_use_incremental_field
                    else {},
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
            },
            "table_format": "delta",
        }

    # Lists endpoint
    if name == "lists":
        return {
            "name": "lists",
            "table_name": "lists",
            **({"primary_key": "id.list_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/lists",
                "data_selector": "data",
                "params": {
                    "limit": 100,
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
            },
            "table_format": "delta",
        }

    # List entries - this is more complex as we need to query all lists first
    # For now, we'll just get entries without filtering by list
    if name == "list_entries":
        return {
            "name": "list_entries",
            "table_name": "list_entries",
            **({"primary_key": "id.entry_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/entries/query",
                "method": "POST",
                "data_selector": "data",
                "json": {
                    "limit": 100,
                    "sorts": [{"attribute": "created_at", "direction": "asc"}]
                    if should_use_incremental_field
                    else [],
                    "filter": {
                        "created_at": {
                            "type": "incremental",
                            "cursor_path": "created_at",
                            "initial_value": "1970-01-01T00:00:00Z",
                        }
                    }
                    if should_use_incremental_field
                    else {},
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
            },
            "table_format": "delta",
        }

    # Notes endpoint
    if name == "notes":
        return {
            "name": "notes",
            "table_name": "notes",
            **({"primary_key": "id.note_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/notes",
                "data_selector": "data",
                "params": {
                    "limit": 100,
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
            },
            "table_format": "delta",
        }

    # Tasks endpoint
    if name == "tasks":
        return {
            "name": "tasks",
            "table_name": "tasks",
            **({"primary_key": "id.task_id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "path": "/v2/tasks",
                "data_selector": "data",
                "params": {
                    "limit": 100,
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
            },
            "table_format": "delta",
        }

    # Workspace members endpoint
    if name == "workspace_members":
        return {
            "name": "workspace_members",
            "table_name": "workspace_members",
            **({"primary_key": "id.workspace_member_id"} if should_use_incremental_field else {}),
            "write_disposition": "replace",  # Workspace members don't have incremental support
            "endpoint": {
                "path": "/v2/workspace_members",
                "data_selector": "data",
                "params": {
                    "limit": 100,
                },
                "paginator": {
                    "type": "offset",
                    "limit": 100,
                    "offset_param": "offset",
                },
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
    yield from dlt_resources[0]


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
