from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Square API endpoints
PAYMENTS = "payments"
CUSTOMERS = "customers"
ORDERS = "orders"
ITEMS = "items"
CATEGORIES = "categories"
DISCOUNTS = "discounts"
TAXES = "taxes"
MODIFIER_LISTS = "modifier_lists"
REFUNDS = "refunds"
LOCATIONS = "locations"
TEAM_MEMBERS = "team_members"
SHIFTS = "shifts"
INVENTORY = "inventory"

ENDPOINTS = [
    PAYMENTS,
    CUSTOMERS,
    ORDERS,
    ITEMS,
    CATEGORIES,
    DISCOUNTS,
    TAXES,
    MODIFIER_LISTS,
    REFUNDS,
    LOCATIONS,
    TEAM_MEMBERS,
    SHIFTS,
    INVENTORY,
]

# Incremental fields for each endpoint
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    PAYMENTS: [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    CUSTOMERS: [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    ORDERS: [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    ITEMS: [
        {
            "label": "Updated at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    CATEGORIES: [
        {
            "label": "Updated at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    DISCOUNTS: [
        {
            "label": "Updated at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    TAXES: [
        {
            "label": "Updated at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    MODIFIER_LISTS: [
        {
            "label": "Updated at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    REFUNDS: [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    SHIFTS: [
        {
            "label": "Created at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
