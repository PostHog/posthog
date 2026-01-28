from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MailjetEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 1000  # Mailjet max is 1000
    # Filter parameter name for incremental sync (e.g., "FromTS" for timestamp filtering)
    # If None, endpoint doesn't support timestamp-based filtering
    incremental_filter_param: Optional[str] = None
    sort: Optional[str] = None


MAILJET_ENDPOINTS: dict[str, MailjetEndpointConfig] = {
    "contactslist": MailjetEndpointConfig(
        name="contactslist",
        path="/contactslist",
        # contactslist doesn't have timestamp fields for incremental sync
        incremental_fields=[],
    ),
    "contacts": MailjetEndpointConfig(
        name="contacts",
        path="/contact",
        # Contact has LastActivityAt but no filter parameter for it
        # We can track the field for upsert but must re-fetch all contacts
        default_incremental_field="LastActivityAt",
        incremental_fields=[
            {
                "label": "LastActivityAt",
                "type": IncrementalFieldType.DateTime,
                "field": "LastActivityAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort="LastActivityAt DESC",
    ),
    "campaign": MailjetEndpointConfig(
        name="campaign",
        path="/campaign",
        default_incremental_field="CreatedAt",
        partition_key="CreatedAt",
        # Campaign supports FromTS filter for CreatedAt
        incremental_filter_param="FromTS",
        incremental_fields=[
            {
                "label": "CreatedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "CreatedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort="CreatedAt DESC",
    ),
    "message": MailjetEndpointConfig(
        name="message",
        path="/message",
        default_incremental_field="ArrivedAt",
        partition_key="ArrivedAt",
        # Message supports FromTS filter for ArrivedAt
        incremental_filter_param="FromTS",
        incremental_fields=[
            {
                "label": "ArrivedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "ArrivedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort="ArrivedAt DESC",
    ),
    "listrecipient": MailjetEndpointConfig(
        name="listrecipient",
        path="/listrecipient",
        # listrecipient has SubscribedAt but no documented filter for it
        default_incremental_field="SubscribedAt",
        incremental_fields=[
            {
                "label": "SubscribedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "SubscribedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(MAILJET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILJET_ENDPOINTS.items()
}
