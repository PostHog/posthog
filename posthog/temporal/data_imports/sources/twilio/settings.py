from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = [
    "accounts",
    "addresses",
    "calls",
    "conferences",
    "messages",
    "available_phone_numbers_local",
    "available_phone_numbers_mobile",
    "available_phone_numbers_toll_free",
    "usage_records",
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "calls": [
        {
            "label": "Date created",
            "type": IncrementalFieldType.DateTime,
            "field": "date_created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "messages": [
        {
            "label": "Date created",
            "type": IncrementalFieldType.DateTime,
            "field": "date_created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "conferences": [
        {
            "label": "Date created",
            "type": IncrementalFieldType.DateTime,
            "field": "date_created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "addresses": [
        {
            "label": "Date created",
            "type": IncrementalFieldType.DateTime,
            "field": "date_created",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
