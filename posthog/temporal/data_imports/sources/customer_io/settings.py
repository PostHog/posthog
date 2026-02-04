from dataclasses import dataclass


@dataclass
class CustomerIOEndpointConfig:
    name: str
    path: str
    data_selector: str = "customers"
    partition_key: str | None = None
    page_size: int = 100
    # If True, this endpoint requires custom handling (not standard REST)
    custom_handler: bool = False


# Customer.io App API endpoints
# Note: Customer.io API does not support filtering by updated_at for most endpoints,
# so only full refresh is supported.
CUSTOMERIO_ENDPOINTS: dict[str, CustomerIOEndpointConfig] = {
    "customers": CustomerIOEndpointConfig(
        name="customers",
        path="/segments/{segment_id}/membership",
        data_selector="identifiers",
        custom_handler=True,  # Requires fetching segments first, uses membership endpoint
    ),
    "segments": CustomerIOEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
    ),
    "campaigns": CustomerIOEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        partition_key="created",
    ),
    "newsletters": CustomerIOEndpointConfig(
        name="newsletters",
        path="/newsletters",
        data_selector="newsletters",
        partition_key="created",
    ),
    "activities": CustomerIOEndpointConfig(
        name="activities",
        path="/activities",
        data_selector="activities",
    ),
}

ENDPOINTS = tuple(CUSTOMERIO_ENDPOINTS.keys())
