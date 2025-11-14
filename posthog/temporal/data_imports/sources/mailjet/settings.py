from products.data_warehouse.backend.types import IncrementalField

ENDPOINTS = (
    "contactslist",
    "contacts",
    "campaign",
    "message",
    "listrecipient",
)

# Mailjet API doesn't provide standard incremental fields like created_at or updated_at
# For most endpoints, we'll use full refresh syncs
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
