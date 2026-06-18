from dataclasses import dataclass, field

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# The only attributes Gorgias accepts in `order_by` (each as `<field>:asc|desc`).
# Gorgias exposes no server-side timestamp filter, so incremental sync is done by
# sorting on one of these descending and stopping pagination at the watermark.
VALID_SORT_FIELDS = frozenset({"created_datetime", "updated_datetime"})


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
    # Whether this endpoint can sync incrementally. Gorgias has no server-side time
    # filter, so incremental relies on sorting the cursor `<field>:desc` and halting
    # once a whole page predates the watermark. Only safe when the advertised cursor
    # field actually reflects the change we care about: `updated_datetime` for mutable
    # resources, `created_datetime` for append-only ones. Mutable config tables that
    # expose only `created_datetime` (tags/views/teams/macros) stay full-refresh,
    # since incremental there would silently miss edits.
    supports_incremental: bool = False
    # Cursor fields offered to the user. Only advertise a field whose desc-sort yields
    # correct incremental semantics for this resource.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


GORGIAS_ENDPOINTS: dict[str, GorgiasEndpointConfig] = {
    "tickets": GorgiasEndpointConfig(
        name="tickets",
        path="/tickets",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_datetime")],
    ),
    "messages": GorgiasEndpointConfig(
        name="messages",
        path="/messages",
        supports_incremental=True,
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "customers": GorgiasEndpointConfig(
        name="customers",
        path="/customers",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_datetime")],
    ),
    "users": GorgiasEndpointConfig(
        name="users",
        path="/users",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_datetime")],
    ),
    "satisfaction_surveys": GorgiasEndpointConfig(
        name="satisfaction_surveys",
        path="/satisfaction-surveys",
        supports_incremental=True,
        incremental_fields=[_datetime_field("created_datetime")],
    ),
    "tags": GorgiasEndpointConfig(
        name="tags",
        path="/tags",
    ),
    "views": GorgiasEndpointConfig(
        name="views",
        path="/views",
    ),
    "teams": GorgiasEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "macros": GorgiasEndpointConfig(
        name="macros",
        path="/macros",
    ),
}

ENDPOINTS = tuple(GORGIAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GORGIAS_ENDPOINTS.items()
}
