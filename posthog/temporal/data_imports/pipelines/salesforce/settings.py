from posthog.warehouse.types import IncrementalField
from posthog.warehouse.types import IncrementalFieldType

INCREMENTAL_ENDPOINTS = ("Account",)

ENDPOINTS = [
    *INCREMENTAL_ENDPOINTS,
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "User": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "UserRole": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Lead": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Contact": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Campaign": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Product2": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Pricebook2": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "PricebookEntry": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Order": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Account": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
