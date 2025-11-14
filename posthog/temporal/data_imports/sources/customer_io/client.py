"""Customer.io API client for data imports"""

from collections.abc import Generator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.customer_io.constants import (
    ACTIVITIES_RESOURCE_NAME,
    CAMPAIGNS_RESOURCE_NAME,
    NEWSLETTERS_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.customer_io.settings import (
    EU_API_BASE_URL,
    INCREMENTAL_FIELDS,
    US_API_BASE_URL,
)


class CustomerIOAPIError(Exception):
    """Exception raised for Customer.io API errors"""

    pass


class CustomerIOPermissionError(Exception):
    """Exception raised for permission-related errors"""

    pass


def get_api_base_url(region: str) -> str:
    """Get the appropriate API base URL based on region"""
    if region.lower() == "eu":
        return EU_API_BASE_URL
    return US_API_BASE_URL


def validate_credentials(app_api_key: str, region: str) -> bool:
    """
    Validate Customer.io API credentials by making a test request.
    Uses the campaigns endpoint as it's a simple read-only endpoint.
    """
    base_url = get_api_base_url(region)
    url = f"{base_url}/api/campaigns"

    headers = {"Authorization": f"Bearer {app_api_key}", "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers, params={"start": "0", "limit": "1"}, timeout=10)

        if response.status_code == 401:
            return False
        elif response.status_code == 403:
            raise CustomerIOPermissionError("API key lacks required permissions")
        elif response.status_code >= 400:
            raise CustomerIOAPIError(f"API request failed with status {response.status_code}: {response.text}")

        return True
    except requests.exceptions.RequestException as e:
        raise CustomerIOAPIError(f"Failed to connect to Customer.io API: {str(e)}")


def get_campaigns(
    app_api_key: str,
    region: str,
    logger: FilteringBoundLogger,
    start_timestamp: int | None = None,
) -> Generator[list[dict[str, Any]], None, None]:
    """Fetch campaigns from Customer.io API"""
    base_url = get_api_base_url(region)
    url = f"{base_url}/api/campaigns"

    headers = {"Authorization": f"Bearer {app_api_key}", "Content-Type": "application/json"}

    start = 0
    limit = 100
    batcher = Batcher(logger=logger)

    while True:
        params: dict[str, Any] = {"start": str(start), "limit": str(limit)}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            campaigns = data.get("campaigns", [])

            if not campaigns:
                break

            for campaign in campaigns:
                # Filter by timestamp if doing incremental sync
                if start_timestamp and campaign.get("created", 0) <= start_timestamp:
                    continue

                batcher.batch(campaign)

                if batcher.should_yield():
                    yield batcher.get_rows()

            # Check if we've reached the end
            if len(campaigns) < limit:
                break

            start += limit

        except requests.exceptions.RequestException as e:
            logger.exception("Error fetching campaigns from Customer.io")
            raise CustomerIOAPIError(f"Failed to fetch campaigns: {str(e)}")

    # Yield any remaining items
    if batcher.has_items():
        yield batcher.get_rows()


def get_newsletters(
    app_api_key: str,
    region: str,
    logger: FilteringBoundLogger,
    start_timestamp: int | None = None,
) -> Generator[list[dict[str, Any]], None, None]:
    """Fetch newsletters from Customer.io API"""
    base_url = get_api_base_url(region)
    url = f"{base_url}/api/newsletters"

    headers = {"Authorization": f"Bearer {app_api_key}", "Content-Type": "application/json"}

    start = 0
    limit = 100
    batcher = Batcher(logger=logger)

    while True:
        params: dict[str, Any] = {"start": str(start), "limit": str(limit)}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            newsletters = data.get("newsletters", [])

            if not newsletters:
                break

            for newsletter in newsletters:
                # Filter by timestamp if doing incremental sync
                if start_timestamp and newsletter.get("created", 0) <= start_timestamp:
                    continue

                batcher.batch(newsletter)

                if batcher.should_yield():
                    yield batcher.get_rows()

            # Check if we've reached the end
            if len(newsletters) < limit:
                break

            start += limit

        except requests.exceptions.RequestException as e:
            logger.exception("Error fetching newsletters from Customer.io")
            raise CustomerIOAPIError(f"Failed to fetch newsletters: {str(e)}")

    # Yield any remaining items
    if batcher.has_items():
        yield batcher.get_rows()


def get_activities(
    app_api_key: str,
    region: str,
    logger: FilteringBoundLogger,
    start_timestamp: int | None = None,
) -> Generator[list[dict[str, Any]], None, None]:
    """Fetch activities from Customer.io API"""
    base_url = get_api_base_url(region)
    url = f"{base_url}/api/activities"

    headers = {"Authorization": f"Bearer {app_api_key}", "Content-Type": "application/json"}

    start = 0
    limit = 100
    batcher = Batcher(logger=logger)

    while True:
        params: dict[str, Any] = {"start": str(start), "limit": str(limit)}

        # Add timestamp filter for incremental sync
        if start_timestamp:
            params["start_timestamp"] = str(start_timestamp)

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            activities = data.get("activities", [])

            if not activities:
                break

            for activity in activities:
                batcher.batch(activity)

                if batcher.should_yield():
                    yield batcher.get_rows()

            # Check if we've reached the end
            if len(activities) < limit:
                break

            start += limit

        except requests.exceptions.RequestException as e:
            logger.exception("Error fetching activities from Customer.io")
            raise CustomerIOAPIError(f"Failed to fetch activities: {str(e)}")

    # Yield any remaining items
    if batcher.has_items():
        yield batcher.get_rows()


def customerio_source(
    app_api_key: str,
    region: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """
    Main source function for Customer.io data imports.

    Args:
        app_api_key: Customer.io App API Key
        region: Region (us or eu)
        endpoint: The endpoint to sync (campaigns, newsletters, or activities)
        should_use_incremental_field: Whether to use incremental sync
        db_incremental_field_last_value: Last synced timestamp for incremental sync
        logger: Logger instance
    """

    # Determine the start timestamp for incremental sync
    start_timestamp = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start_timestamp = int(db_incremental_field_last_value)

    # Select the appropriate endpoint function
    endpoint_functions = {
        CAMPAIGNS_RESOURCE_NAME: get_campaigns,
        NEWSLETTERS_RESOURCE_NAME: get_newsletters,
        ACTIVITIES_RESOURCE_NAME: get_activities,
    }

    endpoint_function = endpoint_functions.get(endpoint)
    if not endpoint_function:
        raise ValueError(f"Unsupported endpoint: {endpoint}")

    logger.info(f"Customer.io: syncing {endpoint}", extra={"incremental": should_use_incremental_field})

    # Get incremental field configuration
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    def items_generator():
        yield from endpoint_function(
            app_api_key=app_api_key,
            region=region,
            logger=logger,
            start_timestamp=start_timestamp,
        )

    return SourceResponse(
        items=items_generator(),
        primary_keys=["id"] if endpoint != ACTIVITIES_RESOURCE_NAME else None,
        incremental_field=incremental_field_name,
        partition_keys=["id"] if endpoint != ACTIVITIES_RESOURCE_NAME else None,
        partition_mode="md5" if endpoint != ACTIVITIES_RESOURCE_NAME else None,
        partition_count=128 if endpoint != ACTIVITIES_RESOURCE_NAME else None,
    )
