from posthog.warehouse.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Organizations",
    "Accounts",
    "Users",
    "Conversations",
    "Notes",
    "Projects",
    "Tasks",
    "NPS_Responses",
    "Custom_Objects",
    "Messages",
)

INCREMENTAL_ENDPOINTS = (
    "Organizations",
    "Accounts",
    "Users",
    "Conversations",
    "Notes",
    "Projects",
    "Tasks",
    "NPS_Responses",
    "Custom_Objects",
    "Messages",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Organizations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Accounts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Users": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Conversations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Notes": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Projects": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Tasks": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "NPS_Responses": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Custom_Fields": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Custom_Objects": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Messages": [
        {
            "label": "conversation_updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "conversation_updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
