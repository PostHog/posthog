from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Common endpoints from Customer.io App API
# These are reporting/read endpoints from the App API
ENDPOINTS = (
    "campaigns",
    "newsletters",
    "messages",
    "actions",
    "segments",
    "broadcasts",
)

# Customer.io uses timestamp-based incremental fields
# Most endpoints support filtering by updated_at or created_at
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "campaigns": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "newsletters": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "messages": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "actions": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "segments": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "broadcasts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
