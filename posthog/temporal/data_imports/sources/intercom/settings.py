from dataclasses import dataclass

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class IntercomEndpointConfig:
    name: str
    path: str
    data_selector: str
    partition_key: str | None = None
    page_size: int = 50
    supports_pagination: bool = True
    # Companies use POST to /companies/list with JSON body pagination
    uses_post_pagination: bool = False


INTERCOM_ENDPOINTS: dict[str, IntercomEndpointConfig] = {
    "contacts": IntercomEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="data",
        partition_key="created_at",
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations",
        data_selector="conversations",
        partition_key="created_at",
    ),
    "companies": IntercomEndpointConfig(
        name="companies",
        path="/companies/list",
        data_selector="data",
        partition_key="created_at",
        uses_post_pagination=True,
    ),
    "admins": IntercomEndpointConfig(
        name="admins",
        path="/admins",
        data_selector="admins",
        supports_pagination=False,
    ),
    "tags": IntercomEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="data",
        supports_pagination=False,
    ),
    "teams": IntercomEndpointConfig(
        name="teams",
        path="/teams",
        data_selector="teams",
        supports_pagination=False,
    ),
    "data_attributes": IntercomEndpointConfig(
        name="data_attributes",
        path="/data_attributes",
        data_selector="data",
        supports_pagination=False,
    ),
}

ENDPOINTS = tuple(INTERCOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "contacts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "conversations": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

PARTITION_FIELDS: dict[str, str] = {
    "contacts": "created_at",
    "conversations": "created_at",
    "companies": "created_at",
}
