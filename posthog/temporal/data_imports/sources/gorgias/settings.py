from dataclasses import dataclass, field

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class GorgiasEndpointConfig:
    name: str
    path: str
    # Stable creation-time field used for datetime partitioning. Gorgias exposes
    # `created_datetime` on every list resource and it never changes once set —
    # never partition on `updated_datetime`, which rewrites partitions on each sync.
    partition_key: str = "created_datetime"
    # Explicit ascending sort on the stable creation field keeps page boundaries
    # stable across a full-refresh sync even if rows are inserted while we paginate.
    # Every list endpoint accepts `created_datetime:asc` (verified against the docs).
    order_by: str = "created_datetime:asc"
    # Candidate cursor fields surfaced for documentation/forward-compat only. Gorgias
    # list endpoints expose NO server-side timestamp filter (only `order_by`), so true
    # incremental sync is impossible today — every endpoint runs as a full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


GORGIAS_ENDPOINTS: dict[str, GorgiasEndpointConfig] = {
    "tickets": GorgiasEndpointConfig(
        name="tickets",
        path="/tickets",
        incremental_fields=[_datetime_field("created_datetime"), _datetime_field("updated_datetime")],
    ),
    "messages": GorgiasEndpointConfig(
        name="messages",
        path="/messages",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "customers": GorgiasEndpointConfig(
        name="customers",
        path="/customers",
        incremental_fields=[_datetime_field("created_datetime"), _datetime_field("updated_datetime")],
    ),
    "users": GorgiasEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[_datetime_field("created_datetime"), _datetime_field("updated_datetime")],
    ),
    "satisfaction_surveys": GorgiasEndpointConfig(
        name="satisfaction_surveys",
        path="/satisfaction-surveys",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "tags": GorgiasEndpointConfig(
        name="tags",
        path="/tags",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "views": GorgiasEndpointConfig(
        name="views",
        path="/views",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "teams": GorgiasEndpointConfig(
        name="teams",
        path="/teams",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "macros": GorgiasEndpointConfig(
        name="macros",
        path="/macros",
        incremental_fields=[_datetime_field("created_datetime")],
    ),
}

ENDPOINTS = tuple(GORGIAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GORGIAS_ENDPOINTS.items()
}
