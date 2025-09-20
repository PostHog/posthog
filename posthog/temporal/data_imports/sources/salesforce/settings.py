from posthog.warehouse.types import IncrementalField, IncrementalFieldType

INCREMENTAL_ENDPOINTS = (
    "Account",
    "Event",
    "User",
    "UserRole",
    "Lead",
    "Contact",
    "Campaign",
    "Product2",
    "Pricebook2",
    "PricebookEntry",
    "Order",
    "Opportunity",
    "Task",
)

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
    "Opportunity": [
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
    "Event": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "Task": [
        {
            "label": "SystemModstamp",
            "type": IncrementalFieldType.DateTime,
            "field": "SystemModstamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
