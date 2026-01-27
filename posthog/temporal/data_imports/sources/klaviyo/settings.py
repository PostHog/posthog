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
            "label": "attributes.updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "updated_at"],
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes.created_at",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "created_at"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "sms_campaigns": [
        {
            "label": "attributes.updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "updated_at"],
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes.created_at",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "created_at"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "events": [
        {
            "label": "attributes.datetime",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "datetime"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "flows": [
        {
            "label": "attributes.updated",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "updated"],
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes.created",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "created"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "lists": [
        {
            "label": "attributes.updated",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "updated"],
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes.created",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "created"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "profiles": [
        {
            "label": "attributes.updated",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "updated"],
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes.created",
            "type": IncrementalFieldType.DateTime,
            "field": ["attributes", "created"],
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
