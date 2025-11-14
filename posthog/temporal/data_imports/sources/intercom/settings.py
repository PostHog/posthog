"""Intercom source settings and constants"""

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Base URL for Intercom API
BASE_URL = "https://api.intercom.io"

# Endpoints that will be available for syncing
# Based on Airbyte, Fivetran, and Stitch implementations
ENDPOINTS = (
    "admins",
    "companies",
    "company_attributes",
    "contacts",
    "contact_attributes",
    "conversations",
    "segments",
    "tags",
    "teams",
    "tickets",
)

# Endpoints that support incremental syncing
INCREMENTAL_ENDPOINTS = (
    "companies",
    "contacts",
    "conversations",
    "segments",
    "tickets",
)

# Define incremental fields for each endpoint
# Most Intercom resources use 'updated_at' for incremental syncing
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "companies": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "contacts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "conversations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "segments": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "tickets": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}

# Partition keys for each endpoint
# Using created_at when available as it's stable (doesn't change)
# Falls back to id for resources without created_at
PARTITION_FIELDS: dict[str, str] = {
    "admins": "id",
    "companies": "created_at",
    "contacts": "created_at",
    "conversations": "created_at",
    "segments": "id",
    "tickets": "created_at",
    "tags": "id",
    "teams": "id",
}
