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
            "label": "attributes__updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes__created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "sms_campaigns": [
        {
            "label": "attributes__updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes__created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "events": [
        {
            "label": "attributes__datetime",
            "type": IncrementalFieldType.DateTime,
            "field": "datetime",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "flows": [
        {
            "label": "attributes__updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes__created",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "lists": [
        {
            "label": "attributes__updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes__created",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "profiles": [
        {
            "label": "attributes__updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "attributes__created",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
