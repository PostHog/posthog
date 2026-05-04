from dataclasses import dataclass
from typing import Literal

PaginatorKind = Literal["single", "cursor", "next_url"]
PartitionMode = Literal["md5", "datetime"]


@dataclass
class IntercomEndpointConfig:
    name: str
    path: str
    data_selector: str
    paginator_kind: PaginatorKind
    primary_key: str = "id"
    partition_key: str = "created_at"
    partition_mode: PartitionMode = "datetime"
    partition_format: str | None = "month"
    partition_count: int = 1
    partition_size: int = 1
    page_size: int = 150


# Endpoint contracts validated against the live Intercom REST API (version 2.13).
# Selectors, pagination shape, and partition keys reflect what the API actually
# returns — not the docs.
INTERCOM_ENDPOINTS: dict[str, IntercomEndpointConfig] = {
    "admins": IntercomEndpointConfig(
        name="admins",
        path="/admins",
        data_selector="admins",
        paginator_kind="single",
        partition_key="id",
        partition_mode="md5",
        partition_format=None,
    ),
    "teams": IntercomEndpointConfig(
        name="teams",
        path="/teams",
        data_selector="teams",
        paginator_kind="single",
        partition_key="id",
        partition_mode="md5",
        partition_format=None,
    ),
    "tags": IntercomEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="data",
        paginator_kind="single",
        partition_key="id",
        partition_mode="md5",
        partition_format=None,
    ),
    "segments": IntercomEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
        paginator_kind="single",
    ),
    "companies": IntercomEndpointConfig(
        name="companies",
        path="/companies",
        data_selector="data",
        paginator_kind="next_url",
    ),
    "contacts": IntercomEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="data",
        paginator_kind="cursor",
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations",
        data_selector="conversations",
        paginator_kind="cursor",
    ),
    "articles": IntercomEndpointConfig(
        name="articles",
        path="/articles",
        data_selector="data",
        paginator_kind="next_url",
    ),
}

ENDPOINTS = tuple(INTERCOM_ENDPOINTS.keys())
