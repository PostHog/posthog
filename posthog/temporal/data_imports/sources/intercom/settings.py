from dataclasses import dataclass
from typing import Literal

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class IntercomEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: str = "id"
    partition_key: str = "updated_at"
    method: Literal["GET", "POST"] = "GET"
    page_size: int = 150
    paginated: bool = True


INTERCOM_ENDPOINTS: dict[str, IntercomEndpointConfig] = {
    "contacts": IntercomEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="data",
    ),
    "companies": IntercomEndpointConfig(
        name="companies",
        path="/companies/list",
        data_selector="data",
        method="POST",
        page_size=50,
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations",
        data_selector="conversations",
    ),
    "admins": IntercomEndpointConfig(
        name="admins",
        path="/admins",
        data_selector="admins",
        paginated=False,
    ),
    "tags": IntercomEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="data",
        paginated=False,
    ),
    "teams": IntercomEndpointConfig(
        name="teams",
        path="/teams",
        data_selector="teams",
        paginated=False,
    ),
    "segments": IntercomEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
        paginated=False,
    ),
}

ENDPOINTS = tuple(INTERCOM_ENDPOINTS.keys())

_UPDATED_AT_FIELD: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.Integer,
        "field": "updated_at",
        "field_type": IncrementalFieldType.Integer,
    },
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "contacts": _UPDATED_AT_FIELD,
    "companies": _UPDATED_AT_FIELD,
    "conversations": _UPDATED_AT_FIELD,
}
