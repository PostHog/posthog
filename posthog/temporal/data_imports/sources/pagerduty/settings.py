from dataclasses import dataclass, field
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PagerDutyEndpointConfig:
    name: str
    path: str  # Path under the API base URL, e.g. "/incidents"
    envelope_key: str  # Key the list of objects is wrapped under in the response body
    primary_key: str = "id"
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the endpoint exposes a server-side `since` filter on created_at AND
    # accepts a `sort_by=created_at:asc` ordering we control. Both are required for safe
    # incremental sync: the filter bounds the window, the sort guarantees a stable
    # ascending watermark. Endpoints without a controllable sort stay full-refresh so the
    # cursor can't advance past unread rows.
    supports_since: bool = False


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


PAGERDUTY_ENDPOINTS: dict[str, PagerDutyEndpointConfig] = {
    "incidents": PagerDutyEndpointConfig(
        name="incidents",
        path="/incidents",
        envelope_key="incidents",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        # `since`/`until` filter incidents by created_at and `sort_by=created_at:asc` is
        # supported, so incremental sync is safe. Note this only picks up newly *created*
        # incidents — status changes to incidents created before the cursor are not
        # re-fetched (PagerDuty's REST filters key on created_at, not updated_at). Webhooks
        # would be needed for true change capture.
        supports_since=True,
    ),
    "log_entries": PagerDutyEndpointConfig(
        name="log_entries",
        path="/log_entries",
        envelope_key="log_entries",
        partition_key="created_at",
        # `/log_entries` accepts a `since` filter but exposes no controllable sort param, so
        # we can't guarantee an ascending watermark. Ship full refresh rather than risk the
        # cursor advancing past unread rows.
    ),
    "services": PagerDutyEndpointConfig(
        name="services",
        path="/services",
        envelope_key="services",
    ),
    "users": PagerDutyEndpointConfig(
        name="users",
        path="/users",
        envelope_key="users",
    ),
    "teams": PagerDutyEndpointConfig(
        name="teams",
        path="/teams",
        envelope_key="teams",
    ),
    "escalation_policies": PagerDutyEndpointConfig(
        name="escalation_policies",
        path="/escalation_policies",
        envelope_key="escalation_policies",
    ),
    "schedules": PagerDutyEndpointConfig(
        name="schedules",
        path="/schedules",
        envelope_key="schedules",
    ),
    "priorities": PagerDutyEndpointConfig(
        name="priorities",
        path="/priorities",
        envelope_key="priorities",
    ),
    "vendors": PagerDutyEndpointConfig(
        name="vendors",
        path="/vendors",
        envelope_key="vendors",
    ),
}

ENDPOINTS = tuple(PAGERDUTY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PAGERDUTY_ENDPOINTS.items()
}
