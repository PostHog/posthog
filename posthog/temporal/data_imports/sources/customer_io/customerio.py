from collections.abc import Generator
from typing import Any

import requests
import structlog
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.customer_io.settings import CUSTOMERIO_ENDPOINTS

logger = structlog.get_logger(__name__)


def get_base_url(region: str) -> str:
    """Get the base URL for the Customer.io App API based on region."""
    if region == "EU":
        return "https://api-eu.customer.io/v1"
    return "https://api.customer.io/v1"


def get_resource(name: str) -> EndpointResource:
    config = CUSTOMERIO_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


class CustomerIOPaginator(BasePaginator):
    """Paginator for Customer.io API using cursor-based pagination."""

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self._limit = limit
        self._next_cursor: str | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Customer.io uses cursor-based pagination with a "next" field
        # Check for truthy value (not just not None) to handle empty string case
        self._next_cursor = res.get("next")
        self._has_next_page = bool(self._next_cursor)

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._next_cursor:
            if request.params is None:
                request.params = {}
            request.params["start"] = self._next_cursor


# Timestamp fields that need conversion from milliseconds to seconds
TIMESTAMP_FIELDS = [
    "created",
    "updated",
    "created_at",
    "updated_at",
    "last_activity_at",
    "sent_at",
    "opened_at",
    "clicked_at",
    "converted_at",
    "unsubscribed_at",
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Customer.io timestamp fields from milliseconds to seconds if needed."""
    for field in TIMESTAMP_FIELDS:
        if field in item and item[field] is not None:
            # Customer.io returns timestamps in seconds (Unix timestamp)
            # but some fields may be in milliseconds - normalize to seconds
            value = item[field]
            if isinstance(value, int) and value > 10000000000:
                # Likely milliseconds, convert to seconds
                item[field] = value // 1000
    return item


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    """Validate Customer.io API credentials by making a test request."""
    url = f"{get_base_url(region)}/segments"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10, allow_redirects=False)

        if response.status_code == 200:
            return True, None

        if response.status_code in (301, 302, 307, 308):
            other_region = "EU" if region == "US" else "US"
            return False, f"Wrong region selected. Please select {other_region} instead."

        if response.status_code == 401:
            return False, "Invalid API key. Make sure you're using an App API key (not a Track API key)."

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _get_all_customer_ids_from_segments(
    base_url: str,
    headers: dict[str, str],
    page_size: int = 100,
) -> set[str]:
    """
    Collect all unique customer cio_ids by iterating through all segments.
    Returns a set of cio_ids.
    """
    seen_customer_ids: set[str] = set()

    segments_url = f"{base_url}/segments"
    segments_cursor: str | None = None

    while True:
        params: dict[str, Any] = {"limit": page_size}
        if segments_cursor:
            params["start"] = segments_cursor

        response = requests.get(segments_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        segments = data.get("segments") or []
        for segment in segments:
            segment_id = segment.get("id")
            if not segment_id:
                continue

            membership_url = f"{base_url}/segments/{segment_id}/membership"
            membership_cursor: str | None = None

            while True:
                membership_params: dict[str, Any] = {"limit": page_size}
                if membership_cursor:
                    membership_params["start"] = membership_cursor

                membership_response = requests.get(
                    membership_url, headers=headers, params=membership_params, timeout=30
                )
                membership_response.raise_for_status()
                membership_data = membership_response.json()

                identifiers = membership_data.get("identifiers") or []
                for identifier in identifiers:
                    cio_id = identifier.get("cio_id")
                    if cio_id:
                        seen_customer_ids.add(cio_id)

                membership_cursor = membership_data.get("next")
                if not membership_cursor:
                    break

        segments_cursor = data.get("next")
        if not segments_cursor:
            break

    return seen_customer_ids


def _fetch_customer_attributes_batch(
    base_url: str,
    headers: dict[str, str],
    cio_ids: list[str],
) -> list[dict[str, Any]]:
    """
    Fetch full customer attributes for a batch of up to 100 cio_ids.
    Uses POST /v1/customers/attributes endpoint with raw cio_id values.
    """
    url = f"{base_url}/customers/attributes"
    payload = {"ids": cio_ids}

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()

    customers = data.get("customers") or []

    results = []
    for customer_wrapper in customers:
        # Handle both nested {"customer": {...}} and flat {...} structures
        if isinstance(customer_wrapper, dict) and "customer" in customer_wrapper:
            customer = customer_wrapper.get("customer", {})
        else:
            customer = customer_wrapper

        if not customer:
            continue

        record: dict[str, Any] = {}

        identifiers = customer.get("identifiers", {})
        record["cio_id"] = identifiers.get("cio_id")
        record["id"] = identifiers.get("id")
        record["email"] = identifiers.get("email")

        attributes = customer.get("attributes", {})
        for key, value in attributes.items():
            if key not in ("cio_id", "id", "email"):
                record[key] = value

        record["unsubscribed"] = customer.get("unsubscribed", False)

        timestamps = customer.get("timestamps", {})
        if timestamps.get("cio_id"):
            record["created_at"] = timestamps["cio_id"]

        results.append(record)

    return results


def _fetch_customers_via_segments(
    api_key: str,
    region: str,
    page_size: int = 100,
) -> Generator[dict[str, Any], None, None]:
    """
    Fetch all customers with full attributes by:
    1. Collecting all unique customer cio_ids from segment memberships
    2. Fetching full attributes in batches of 100 using POST /v1/customers/attributes
    """
    base_url = get_base_url(region)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Step 1: Collect all unique customer IDs from segments
    all_cio_ids = _get_all_customer_ids_from_segments(base_url, headers, page_size)
    logger.info(f"Customer.io: collected {len(all_cio_ids)} unique customer IDs from segments")

    if not all_cio_ids:
        return

    # Step 2: Fetch full attributes in batches of 100
    cio_ids_list = list(all_cio_ids)
    batch_size = 100
    total_yielded = 0

    for i in range(0, len(cio_ids_list), batch_size):
        batch = cio_ids_list[i : i + batch_size]
        customers = _fetch_customer_attributes_batch(base_url, headers, batch)
        for customer in customers:
            total_yielded += 1
            yield _convert_timestamps(customer)

    logger.info(f"Customer.io: completed - yielded {total_yielded} customers")


def customerio_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = CUSTOMERIO_ENDPOINTS[endpoint]

    # Handle customers specially - requires fetching via segments
    # Uses membership endpoint which returns identifiers with cio_id (always present), id and email (nullable)
    if endpoint_config.custom_handler and endpoint == "customers":
        return SourceResponse(
            name=endpoint,
            items=lambda: _fetch_customers_via_segments(api_key, region, endpoint_config.page_size),
            primary_keys=["cio_id"],
            partition_count=1,
            partition_size=1,
            partition_mode=None,
            partition_format=None,
            partition_keys=None,
        )

    # Standard REST endpoint handling
    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(region),
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": CustomerIOPaginator(limit=endpoint_config.page_size),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "limit": endpoint_config.page_size,
                },
            },
        },
        "resources": [get_resource(endpoint)],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0].add_map(_convert_timestamps)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
