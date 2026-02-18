from dataclasses import dataclass
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MailchimpEndpointConfig:
    name: str
    path: str
    data_selector: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 1000  # Mailchimp max is 1000


MAILCHIMP_ENDPOINTS: dict[str, MailchimpEndpointConfig] = {
    "lists": MailchimpEndpointConfig(
        name="lists",
        path="/lists",
        data_selector="lists",
        incremental_fields=[],
        partition_key="date_created",
    ),
    "campaigns": MailchimpEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        incremental_fields=[],
        partition_key="create_time",
    ),
    "reports": MailchimpEndpointConfig(
        name="reports",
        path="/reports",
        data_selector="reports",
        incremental_fields=[],
        partition_key="send_time",
    ),
    "contacts": MailchimpEndpointConfig(
        name="contacts",
        path="/lists/{list_id}/members",  # Special: iterates over all lists
        data_selector="members",
        partition_key=None,  # No stable timestamp field available
        default_incremental_field="last_changed",
        incremental_fields=[
            {
                "label": "last_changed",
                "type": IncrementalFieldType.DateTime,
                "field": "last_changed",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(MAILCHIMP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILCHIMP_ENDPOINTS.items()
}
