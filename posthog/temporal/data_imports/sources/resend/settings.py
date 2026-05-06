from dataclasses import dataclass
from typing import Optional


@dataclass
class ResendEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    partition_key: Optional[str] = None
    # Cursor-paginated endpoints (e.g. /emails) use `limit` + `after`. Flat endpoints
    # return the full list in a single response, so page_size is None.
    page_size: Optional[int] = None
    # For fan-out endpoints like `contacts`, names the parent endpoint we iterate to
    # resolve the path parameter.
    parent: Optional[str] = None


RESEND_ENDPOINTS: dict[str, ResendEndpointConfig] = {
    "audiences": ResendEndpointConfig(
        name="audiences",
        path="/audiences",
        partition_key="created_at",
    ),
    "broadcasts": ResendEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        partition_key="created_at",
    ),
    "domains": ResendEndpointConfig(
        name="domains",
        path="/domains",
        partition_key="created_at",
    ),
    "emails": ResendEndpointConfig(
        name="emails",
        path="/emails",
        partition_key="created_at",
        page_size=100,
    ),
    "contacts": ResendEndpointConfig(
        name="contacts",
        path="/audiences/{audience_id}/contacts",
        partition_key="created_at",
        parent="audiences",
    ),
}


ENDPOINTS = tuple(RESEND_ENDPOINTS.keys())
