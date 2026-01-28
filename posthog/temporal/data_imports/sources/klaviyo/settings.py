from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "email_campaigns",
    "sms_campaigns",
    "events",
    "flows",
    "lists",
    "metrics",
    "profiles",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "email_campaigns": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "sms_campaigns": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "events": [
        {
            "label": "datetime",
            "type": IncrementalFieldType.DateTime,
            "field": "datetime",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "flows": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "lists": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "profiles": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
