from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Customers",
    "Events",
    "Invoices",
    "Orders",
    "Subscriptions",
    "Transactions",
)

INCREMENTAL_ENDPOINTS = (
    "Customers",
    "Events",
    "Invoices",
    "Orders",
    "Subscriptions",
    "Transactions",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Customers": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Events": [
        {
            "label": "occurred_at",
            "type": IncrementalFieldType.DateTime,
            "field": "occurred_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Invoices": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Orders": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Subscriptions": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "Transactions": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
