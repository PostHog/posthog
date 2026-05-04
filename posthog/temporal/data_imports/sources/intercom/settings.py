from dataclasses import dataclass
from typing import Literal

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

PaginatorKind = Literal["single", "cursor", "next_url", "search"]
PartitionMode = Literal["md5", "datetime"]
HttpMethod = Literal["GET", "POST"]


@dataclass
class IntercomEndpointConfig:
    name: str
    path: str
    data_selector: str
    paginator_kind: PaginatorKind
    method: HttpMethod = "GET"
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
        # `POST /companies/list` is the only paginated company-listing
        # endpoint that's stable in 2.13. `GET /companies` requires a filter
        # param (it's the "Retrieve Companies" lookup, returns 400 without
        # one), and `/companies/scroll` only allows one open cursor per
        # workspace at a time so concurrent or quickly-retried syncs collide.
        # The next-URL pagination shape matches the other list endpoints
        # (`pages.next` is a full URL); the framework follows it by mutating
        # `request.url` while preserving the POST method and body.
        # per_page max is 60 here, not 150 — Intercom rejects larger values
        # with `parameter_invalid: Per Page is too big`.
        name="companies",
        path="/companies/list",
        data_selector="data",
        paginator_kind="next_url",
        method="POST",
        page_size=60,
    ),
    "contacts": IntercomEndpointConfig(
        name="contacts",
        path="/contacts/search",
        data_selector="data",
        paginator_kind="search",
        method="POST",
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations/search",
        data_selector="conversations",
        paginator_kind="search",
        method="POST",
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
