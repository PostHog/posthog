# Drip API endpoints based on Airbyte connector and API documentation
# Reference: https://developer.drip.com/

ENDPOINTS = [
    "accounts",
    "broadcasts",
    "campaigns",
    "subscribers",
    "custom_fields",
    "conversions",
    "events",
    "tags",
    "workflows",
    "forms",
]

# Incremental fields for Drip endpoints
# Most Drip endpoints support filtering by created_at or updated_at
INCREMENTAL_FIELDS: dict[str, list[str]] = {
    "subscribers": ["created_at"],
    "events": ["created_at"],
    "campaigns": ["created_at"],
    "broadcasts": ["created_at"],
    "workflows": ["created_at"],
}
