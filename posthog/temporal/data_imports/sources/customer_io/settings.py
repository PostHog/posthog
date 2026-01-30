from dataclasses import dataclass


@dataclass
class CustomerIOEndpointConfig:
    name: str
    path: str
    data_selector: str = "customers"
    partition_key: str | None = None
    page_size: int = 100


# Customer.io App API endpoints
# Note: Customer.io API does not support filtering by updated_at for most endpoints,
# so only full refresh is supported.
CUSTOMERIO_ENDPOINTS: dict[str, CustomerIOEndpointConfig] = {
    "customers": CustomerIOEndpointConfig(
        name="customers",
        path="/customers",
        data_selector="customers",
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
