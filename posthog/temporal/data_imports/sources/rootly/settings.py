from dataclasses import dataclass, field
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


def _timestamp_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Rootly resources are Rails records that all expose `updated_at` / `created_at`. For mutable
# collections we advertise both: `updated_at` (default, catches edits) and `created_at`.
_UPDATED_THEN_CREATED: list[IncrementalField] = [_timestamp_field("updated_at"), _timestamp_field("created_at")]


@dataclass
class RootlyEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where Rootly exposes a genuine server-side `filter[<field>][gt]` + `sort=<field>`.
    # When True the transport cursors and sorts ascending on the user's chosen incremental field, so
    # rows arrive in watermark order and pagination terminates server-side at the cutoff.
    supports_incremental: bool = False
    # Stable field to partition by — always a creation timestamp, never `updated_at`.
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    page_size: int = 100


# Endpoint catalog. Paths are relative to https://api.rootly.com/v1. The set mirrors the streams a
# user actually wants from an incident-management platform and matches the resource list other
# connectors (Airbyte/Fivetran) expose for Rootly. Every path here was confirmed to be a real route
# against the live API (real routes return 401 on a bad token; unknown routes return 404).
ROOTLY_ENDPOINTS: dict[str, RootlyEndpointConfig] = {
    # High-value, high-volume mutable collections — incremental.
    "incidents": RootlyEndpointConfig(
        name="incidents",
        path="/incidents",
        supports_incremental=True,
        incremental_fields=_UPDATED_THEN_CREATED,
    ),
    "alerts": RootlyEndpointConfig(
        name="alerts",
        path="/alerts",
        supports_incremental=True,
        incremental_fields=_UPDATED_THEN_CREATED,
    ),
    "action_items": RootlyEndpointConfig(
        name="action_items",
        path="/action_items",
        supports_incremental=True,
        incremental_fields=_UPDATED_THEN_CREATED,
    ),
    "post_mortems": RootlyEndpointConfig(
        name="post_mortems",
        path="/post_mortems",
        supports_incremental=True,
        incremental_fields=_UPDATED_THEN_CREATED,
    ),
    # Pulses are the per-incident activity timeline — high volume, so off by default.
    "pulses": RootlyEndpointConfig(
        name="pulses",
        path="/pulses",
        supports_incremental=True,
        incremental_fields=_UPDATED_THEN_CREATED,
        should_sync_default=False,
    ),
    # Configuration / reference resources — small and slowly-changing, so full refresh each sync.
    "users": RootlyEndpointConfig(name="users", path="/users"),
    "teams": RootlyEndpointConfig(name="teams", path="/teams"),
    "services": RootlyEndpointConfig(name="services", path="/services"),
    "functionalities": RootlyEndpointConfig(name="functionalities", path="/functionalities"),
    "environments": RootlyEndpointConfig(name="environments", path="/environments"),
    "severities": RootlyEndpointConfig(name="severities", path="/severities"),
    "incident_types": RootlyEndpointConfig(name="incident_types", path="/incident_types"),
    "schedules": RootlyEndpointConfig(name="schedules", path="/schedules"),
    "escalation_policies": RootlyEndpointConfig(name="escalation_policies", path="/escalation_policies"),
    "workflows": RootlyEndpointConfig(name="workflows", path="/workflows"),
    "causes": RootlyEndpointConfig(name="causes", path="/causes"),
}

ENDPOINTS = tuple(ROOTLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ROOTLY_ENDPOINTS.items()
}
