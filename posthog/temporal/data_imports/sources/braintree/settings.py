from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Transactions",
    "Customers",
    "Subscriptions",
    "Disputes",
    "Plans",
    "MerchantAccounts",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Transactions": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Customers": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Subscriptions": [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "Disputes": [
        {
            "label": "Received date",
            "type": IncrementalFieldType.Date,
            "field": "received_date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
}
