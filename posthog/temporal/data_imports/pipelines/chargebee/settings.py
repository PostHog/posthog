from posthog.warehouse.types import IncrementalField, IncrementalFieldType

# TODO - add more once we know which ones we need
ENDPOINTS = ("Customers",)

INCREMENTAL_ENDPOINTS = ("Customers",)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Customers": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
