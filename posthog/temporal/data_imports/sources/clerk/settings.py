"""Clerk source settings and constants"""

# Common Clerk API endpoints
# Full list: https://clerk.com/docs/reference/backend-api

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "users",
    "sessions",
    "organizations",
    "organization_memberships",
    "organization_invitations",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "users": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "sessions": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "organizations": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "organization_memberships": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "organization_invitations": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.Integer,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
