from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "lists",
    "campaigns",
    "automations",
    "reports",
)

INCREMENTAL_ENDPOINTS = (
    "lists",
    "campaigns",
    "automations",
    "reports",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "lists": [
        {
            "label": "date_created",
            "type": IncrementalFieldType.DateTime,
            "field": "date_created",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "campaigns": [
        {
            "label": "send_time",
            "type": IncrementalFieldType.DateTime,
            "field": "send_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "automations": [
        {
            "label": "create_time",
            "type": IncrementalFieldType.DateTime,
            "field": "create_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "reports": [
        {
            "label": "send_time",
            "type": IncrementalFieldType.DateTime,
            "field": "send_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
