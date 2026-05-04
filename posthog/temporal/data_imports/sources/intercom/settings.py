from dataclasses import dataclass
from typing import Literal

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

PaginatorKind = Literal["single", "cursor", "next_url", "search"]
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
#
# `contacts` and `conversations` use the POST search endpoints so we can
# filter by `updated_at` for incremental sync. The list endpoints don't
# expose that filter. This matches what Airbyte and Stitch do.
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
        path="/contacts/search",
        data_selector="data",
        paginator_kind="search",
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations/search",
        data_selector="conversations",
        paginator_kind="search",
    ),
    "articles": IntercomEndpointConfig(
        name="articles",
        path="/articles",
        data_selector="data",
        paginator_kind="next_url",
    ),
}

ENDPOINTS = tuple(INTERCOM_ENDPOINTS.keys())


# Endpoints that support incremental sync. Intercom's `/contacts/search` and
# `/conversations/search` accept an `updated_at > <unix_ts>` filter on the
# request body; the other resources (admins, teams, tags, segments,
# companies, articles) have no equivalent filter and are full-refresh only —
# matching what Airbyte and Stitch publish for this connector.
#
# `field_type=Integer` because Intercom returns `updated_at` as a Unix epoch
# integer (seconds), not an ISO string. Same shape Stripe uses for `created`.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
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
}
