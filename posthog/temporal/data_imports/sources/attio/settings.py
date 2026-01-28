from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Define all available Attio endpoints
ENDPOINTS = [
    "companies",
    "people",
    "deals",
    "users",
    "workspaces",
    "lists",
    "notes",
    "tasks",
    "workspace_members",
]

# Define incremental fields for each endpoint
# Most Attio objects have a created_at timestamp that can be used for incremental syncing
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "companies": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "people": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "deals": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "users": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "workspaces": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "notes": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "tasks": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
