from dataclasses import dataclass
from typing import Literal, Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AttioEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    primary_key: str = "record_id"
    method: Literal["GET", "POST"] = "GET"
    default_incremental_field: str = "created_at"
    partition_key: Optional[str] = None
    page_size: int = 500


ATTIO_ENDPOINTS: dict[str, AttioEndpointConfig] = {
    "companies": AttioEndpointConfig(
        name="companies",
        path="/v2/objects/companies/records/query",
        method="POST",
        primary_key="record_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "people": AttioEndpointConfig(
        name="people",
        path="/v2/objects/people/records/query",
        method="POST",
        primary_key="record_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "deals": AttioEndpointConfig(
        name="deals",
        path="/v2/objects/deals/records/query",
        method="POST",
        primary_key="record_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "users": AttioEndpointConfig(
        name="users",
        path="/v2/objects/users/records/query",
        method="POST",
        primary_key="record_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "workspaces": AttioEndpointConfig(
        name="workspaces",
        path="/v2/objects/workspaces/records/query",
        method="POST",
        primary_key="record_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "lists": AttioEndpointConfig(
        name="lists",
        path="/v2/lists",
        method="GET",
        primary_key="list_id",
        incremental_fields=[],
    ),
    "notes": AttioEndpointConfig(
        name="notes",
        path="/v2/notes",
        method="GET",
        primary_key="note_id",
        partition_key="created_at",
        page_size=50,
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "tasks": AttioEndpointConfig(
        name="tasks",
        path="/v2/tasks",
        method="GET",
        primary_key="task_id",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "Created at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "workspace_members": AttioEndpointConfig(
        name="workspace_members",
        path="/v2/workspace_members",
        method="GET",
        primary_key="workspace_member_id",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(ATTIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ATTIO_ENDPOINTS.items()
}
