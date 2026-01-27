from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Email Campaigns",
    "SMS Campaigns",
    "Events",
    "Flows",
    "Lists",
    "Metrics",
    "Profiles",
)

INCREMENTAL_ENDPOINTS = (
    "Events",
    "Profiles",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Email Campaigns": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "SMS Campaigns": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Events": [
        {
            "label": "datetime",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__datetime",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Flows": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__updated",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Lists": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__updated",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Profiles": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "attributes__updated",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
