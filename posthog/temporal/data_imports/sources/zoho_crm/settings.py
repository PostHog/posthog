"""Zoho CRM source settings and constants"""

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Standard Zoho CRM modules that are commonly available
# Based on Airbyte, Fivetran documentation and Zoho CRM API docs
ENDPOINTS = (
    "Leads",
    "Contacts",
    "Accounts",
    "Deals",
    "Products",
    "Tasks",
    "Events",
    "Calls",
    "Campaigns",
    "Vendors",
    "Price_Books",
    "Quotes",
    "Sales_Orders",
    "Purchase_Orders",
    "Invoices",
    "Notes",
    "Activities",
)

# All Zoho CRM modules support incremental sync via Created_Time and Modified_Time
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": "Created Time",
            "type": IncrementalFieldType.DateTime,
            "field": "Created_Time",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "Modified Time",
            "type": IncrementalFieldType.DateTime,
            "field": "Modified_Time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]
    for endpoint in ENDPOINTS
}
