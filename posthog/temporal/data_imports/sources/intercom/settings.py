from dataclasses import dataclass, field
from typing import Literal

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

PaginatorKind = Literal["single", "cursor", "next_url", "search", "substream"]
PartitionMode = Literal["md5", "datetime"]
HttpMethod = Literal["GET", "POST"]
SortMode = Literal["asc", "desc"]


@dataclass
class IntercomEndpointConfig:
    name: str
    path: str
    data_selector: str
    paginator_kind: PaginatorKind
    method: HttpMethod = "GET"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str = "created_at"
    partition_mode: PartitionMode = "datetime"
    partition_format: str | None = "month"
    partition_count: int = 1
    partition_size: int = 1
    page_size: int = 150
    sort_mode: SortMode = "asc"
    extra_params: dict[str, str] = field(default_factory=dict)
    # Query-string param Intercom expects for the cursor filter (e.g. "created_at_after"
    # on /admins/activity_logs). Only set on endpoints that filter via query params.
    incremental_query_param: str | None = None
    # Substream wiring — when set, this endpoint is fetched per-row of `parent_endpoint`.
    parent_endpoint: str | None = None


# Endpoint contracts validated against the live Intercom REST API (version 2.13).
# Selectors, pagination shape, and partition keys reflect what the API actually
# returns — not the docs.
#
# Real-incremental endpoints (server-side filter honored): contacts, conversations,
# tickets, activity_logs, conversation_parts (via parent). Everything else is
# full-refresh because Intercom either has no server filter (companies, segments,
# company_segments — Airbyte/Stitch sync these "incrementally" but actually walk
# every page each run) or no timestamp at all (data_attributes).
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
        partition_key="created_at",
    ),
    "conversations": IntercomEndpointConfig(
        name="conversations",
        path="/conversations/search",
        data_selector="conversations",
        paginator_kind="search",
        method="POST",
        partition_key="created_at",
    ),
    "tickets": IntercomEndpointConfig(
        # `POST /tickets/search` mirrors contacts/conversations: it accepts
        # the same `{"field":"updated_at","operator":">","value":<ts>}` body
        # filter and the same cursor pagination shape.
        name="tickets",
        path="/tickets/search",
        data_selector="tickets",
        paginator_kind="search",
        method="POST",
        partition_key="created_at",
    ),
    "articles": IntercomEndpointConfig(
        name="articles",
        path="/articles",
        data_selector="data",
        paginator_kind="next_url",
    ),
    "activity_logs": IntercomEndpointConfig(
        # `GET /admins/activity_logs?created_at_after=<unix_ts>` is honored
        # server-side (verified with future-date probe). The endpoint sorts
        # descending by `created_at` and ignores any `?sort=` param, so
        # SourceResponse declares `sort_mode="desc"` to match.
        name="activity_logs",
        path="/admins/activity_logs",
        data_selector="activity_logs",
        paginator_kind="next_url",
        partition_key="created_at",
        sort_mode="desc",
        incremental_query_param="created_at_after",
    ),
    "company_attributes": IntercomEndpointConfig(
        # `GET /data_attributes?model=company` — built-in plus custom
        # company-level attributes. No `id`/timestamp on rows; primary key
        # is `name` (unique within a model).
        name="company_attributes",
        path="/data_attributes",
        data_selector="data",
        paginator_kind="single",
        primary_keys=["name"],
        partition_key="name",
        partition_mode="md5",
        partition_format=None,
        extra_params={"model": "company"},
    ),
    "contact_attributes": IntercomEndpointConfig(
        name="contact_attributes",
        path="/data_attributes",
        data_selector="data",
        paginator_kind="single",
        primary_keys=["name"],
        partition_key="name",
        partition_mode="md5",
        partition_format=None,
        extra_params={"model": "contact"},
    ),
    "conversation_parts": IntercomEndpointConfig(
        # Substream of `conversations`: walk the same `POST /conversations/search`
        # query (so the parent's `updated_at >` filter is server-honored), then
        # fetch `GET /conversations/{id}` for each parent and yield each part.
        # Effectively real-incremental — only conversations whose `updated_at`
        # advanced are refetched. Each yielded part carries `conversation_id`.
        name="conversation_parts",
        path="",
        data_selector="",
        paginator_kind="substream",
        parent_endpoint="conversations",
        partition_key="created_at",
    ),
    "company_segments": IntercomEndpointConfig(
        # Substream of `companies`. Intercom doesn't expose a server-side
        # filter on either parent or child, so this is full-refresh (matches
        # the new "fake incremental → full refresh" rule). Each yielded
        # segment carries `company_id`.
        name="company_segments",
        path="",
        data_selector="",
        paginator_kind="substream",
        parent_endpoint="companies",
        primary_keys=["company_id", "id"],
        partition_key="id",
        partition_mode="md5",
        partition_format=None,
    ),
}

ENDPOINTS = tuple(INTERCOM_ENDPOINTS.keys())


# Endpoints that support incremental sync via a server-honored filter on the
# request itself — verified empirically against the live API:
# - contacts/conversations/tickets: POST /<resource>/search accepts
#   `{"field":"updated_at","operator":">","value":<unix_ts>}` in the body.
# - activity_logs: GET /admins/activity_logs?created_at_after=<unix_ts>.
# - conversation_parts: child of conversations; the parent's `updated_at >`
#   filter is server-honored, so parents whose timestamp didn't advance
#   aren't refetched.
#
# Companies, segments, and company_segments are intentionally excluded: their
# list endpoints don't accept a timestamp filter, and a "client-side cursor"
# that walks every page each run is identical in API cost to a full refresh.
#
# `field_type=Integer` because Intercom returns Unix epoch seconds, not ISO.
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
    "tickets": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "activity_logs": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "conversation_parts": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
