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
    page_size: int = 100


MAILJET_ENDPOINTS: dict[str, MailjetEndpointConfig] = {
    "contactslist": MailjetEndpointConfig(
        name="contactslist",
        path="/contactslist",
        incremental_fields=[],
    ),
    "contacts": MailjetEndpointConfig(
        name="contacts",
        path="/contact",
        default_incremental_field="LastActivityAt",
        incremental_fields=[
            {
                "label": "LastActivityAt",
                "type": IncrementalFieldType.DateTime,
                "field": "LastActivityAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "campaign": MailjetEndpointConfig(
        name="campaign",
        path="/campaign",
        default_incremental_field="CreatedAt",
        partition_key="CreatedAt",
        incremental_fields=[
            {
                "label": "CreatedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "CreatedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "message": MailjetEndpointConfig(
        name="message",
        path="/message",
        default_incremental_field="ArrivedAt",
        partition_key="ArrivedAt",
        incremental_fields=[
            {
                "label": "ArrivedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "ArrivedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "listrecipient": MailjetEndpointConfig(
        name="listrecipient",
        path="/listrecipient",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(MAILJET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILJET_ENDPOINTS.items()
}
