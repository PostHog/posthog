import base64
from typing import Any, Generator, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.drip.settings import INCREMENTAL_FIELDS

# Drip API base URL
DRIP_API_BASE = "https://api.getdrip.com/v2"

# Default page size for Drip API requests
DEFAULT_PAGE_SIZE = 100


def validate_credentials(api_token: str, account_id: str) -> bool:
    """Validate Drip API credentials by attempting to fetch account information."""
    try:
        headers = _get_auth_headers(api_token)
        response = requests.get(f"{DRIP_API_BASE}/{account_id}/accounts/{account_id}", headers=headers, timeout=30)
        return response.status_code == 200
    except Exception:
        return False


def _get_auth_headers(api_token: str) -> dict[str, str]:
    """Generate authentication headers for Drip API.

    Drip uses Basic Auth with the API token as username and empty password.
    """
    # Create Basic Auth token: base64 encode "api_token:"
    auth_string = f"{api_token}:"
    auth_bytes = auth_string.encode("ascii")
    base64_bytes = base64.b64encode(auth_bytes)
    base64_string = base64_bytes.decode("ascii")

    return {
        "Authorization": f"Basic {base64_string}",
        "Content-Type": "application/json",
        "User-Agent": "PostHog-Data-Warehouse/1.0",
    }


def _fetch_paginated_data(
    api_token: str,
    account_id: str,
    endpoint: str,
    params: Optional[dict[str, Any]] = None,
    logger: Optional[FilteringBoundLogger] = None,
) -> Generator[dict, None, None]:
    """Fetch paginated data from Drip API.

    Args:
        api_token: Drip API token
        account_id: Drip account ID
        endpoint: API endpoint to fetch from
        params: Optional query parameters
        logger: Optional logger instance

    Yields:
        Individual records from the API response
    """
    headers = _get_auth_headers(api_token)
    url = f"{DRIP_API_BASE}/{account_id}/{endpoint}"

    request_params = params.copy() if params else {}
    request_params["per_page"] = DEFAULT_PAGE_SIZE

    page = 1

    while True:
        request_params["page"] = page

        if logger:
            logger.info(f"Fetching Drip {endpoint} page {page}")

        try:
            response = requests.get(url, headers=headers, params=request_params, timeout=60)
            response.raise_for_status()
            data = response.json()

            # Drip API returns data in different structures depending on endpoint
            # Most endpoints return data in a key matching the endpoint name
            records = []

            if endpoint == "accounts":
                records = data.get("accounts", [])
            elif endpoint == "broadcasts":
                records = data.get("broadcasts", [])
            elif endpoint == "campaigns":
                records = data.get("campaigns", [])
            elif endpoint == "subscribers":
                records = data.get("subscribers", [])
            elif endpoint == "custom_fields":
                records = data.get("custom_field_identifiers", [])
            elif endpoint == "conversions":
                records = data.get("goals", [])
            elif endpoint == "events":
                records = data.get("events", [])
            elif endpoint == "tags":
                records = data.get("tags", [])
            elif endpoint == "workflows":
                records = data.get("workflows", [])
            elif endpoint == "forms":
                records = data.get("forms", [])
            else:
                # Generic fallback
                records = data.get(endpoint, data)

            if not records:
                break

            for record in records:
                yield record

            # Check if there are more pages
            # Drip uses links for pagination
            meta = data.get("meta", {})
            if not meta.get("next", None):
                break

            page += 1

        except requests.exceptions.RequestException as e:
            if logger:
                logger.error(f"Error fetching Drip {endpoint}: {str(e)}")
            raise


def drip_source(
    api_token: str,
    account_id: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Create a Drip data source for the pipeline.

    Args:
        api_token: Drip API token
        account_id: Drip account ID
        endpoint: Endpoint to fetch data from
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last synced value for incremental field
        db_incremental_field_earliest_value: Earliest synced value for incremental field
        logger: Logger instance

    Returns:
        SourceResponse with data items and configuration
    """
    params: dict[str, Any] = {}

    # Add incremental filtering if applicable
    incremental_field = None
    if should_use_incremental_field and endpoint in INCREMENTAL_FIELDS:
        incremental_fields = INCREMENTAL_FIELDS[endpoint]
        if incremental_fields:
            incremental_field = incremental_fields[0]

            # Drip API uses date parameters for filtering (if supported)
            # For now, we'll fetch all data and let the pipeline handle incremental logic
            # This can be enhanced later with endpoint-specific filtering
            if db_incremental_field_last_value:
                logger.info(
                    f"Incremental sync for {endpoint} starting from {incremental_field}: {db_incremental_field_last_value}"
                )

    def items_generator():
        """Generator that yields records from Drip API."""
        for record in _fetch_paginated_data(api_token, account_id, endpoint, params, logger):
            yield record

    # Determine primary keys based on endpoint
    primary_keys = ["id"]  # Most Drip endpoints use 'id' as primary key

    # Determine partition configuration
    partition_keys = None
    partition_mode = None
    partition_format = None

    if incremental_field == "created_at":
        partition_keys = ["created_at"]
        partition_mode = "datetime"
        partition_format = "month"

    return SourceResponse(
        items=items_generator(),
        primary_keys=primary_keys,
        incremental_field=incremental_field,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_format=partition_format,
    )
