"""Airtable source settings and constants"""

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Airtable API configuration
AIRTABLE_API_URL = "https://api.airtable.com/v0"
RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_PERIOD = 1.0

# Page size for fetching records
PAGE_SIZE = 100

# Incremental field for all tables - Airtable has a built-in createdTime field
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


def get_incremental_field_for_table() -> list[IncrementalField]:
    """
    Returns the incremental field configuration for Airtable tables.
    All Airtable tables have a createdTime field that can be used for incremental syncs.
    """
    return [
        {
            "label": "Created Time",
            "type": IncrementalFieldType.DateTime,
            "field": "createdTime",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
