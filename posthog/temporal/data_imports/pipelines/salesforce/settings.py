from posthog.warehouse.types import IncrementalField
from posthog.warehouse.types import IncrementalFieldType

INCREMENTAL_ENDPOINTS = ("Account",)

ENDPOINTS = [
    *("User", "UserRole", "Lead", "Contact", "Campaign", "Product2", "Pricebook2", "PricebookEntry", "Order"),
    *INCREMENTAL_ENDPOINTS,
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Account": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
}
