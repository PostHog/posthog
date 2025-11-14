"""Zoho CRM API client for data warehouse imports"""

from datetime import datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.zoho_crm.settings import INCREMENTAL_FIELDS


class ZohoCRMClient:
    """Client for interacting with Zoho CRM API v6"""

    def __init__(
        self,
        access_token: str,
        api_domain: str,
        logger: FilteringBoundLogger,
    ):
        self.access_token = access_token
        self.api_domain = api_domain
        self.logger = logger
        self.base_url = f"{api_domain}/crm/v6"
        self.headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def get_records(
        self,
        module: str,
        page: int = 1,
        per_page: int = 200,
        sort_by: str | None = None,
        sort_order: str = "asc",
        modified_since: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Fetch records from a Zoho CRM module.

        Args:
            module: The module API name (e.g., "Leads", "Contacts")
            page: Page number (for records under 2000)
            per_page: Records per page (max 200)
            sort_by: Field to sort by (e.g., "Created_Time", "Modified_Time")
            sort_order: Sort order ("asc" or "desc")
            modified_since: Filter records modified after this datetime

        Returns:
            API response containing records and pagination info
        """
        url = f"{self.base_url}/{module}"
        params: dict[str, Any] = {
            "page": page,
            "per_page": min(per_page, 200),  # Max 200 per page
        }

        if sort_by:
            params["sort_by"] = sort_by
            params["sort_order"] = sort_order

        if modified_since:
            # Zoho expects ISO 8601 format
            params["modified_since"] = modified_since.strftime("%Y-%m-%dT%H:%M:%S%z")

        self.logger.debug(f"Zoho CRM: Fetching {module} with params: {params}")

        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code != 200:
            self.logger.error(f"Zoho CRM API error: {response.status_code} - {response.text}")
            raise Exception(f"Zoho CRM API error: {response.status_code} - {response.text}")

        return response.json()

    def get_records_with_page_token(
        self,
        module: str,
        page_token: str | None = None,
        per_page: int = 200,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> dict[str, Any]:
        """
        Fetch records using page token for large datasets (>2000 records).

        Args:
            module: The module API name
            page_token: Token for next page
            per_page: Records per page (max 200)
            sort_by: Field to sort by
            sort_order: Sort order ("asc" or "desc")

        Returns:
            API response containing records and pagination info
        """
        url = f"{self.base_url}/{module}"
        params: dict[str, Any] = {
            "per_page": min(per_page, 200),
        }

        if page_token:
            params["page_token"] = page_token

        if sort_by:
            params["sort_by"] = sort_by
            params["sort_order"] = sort_order

        self.logger.debug(f"Zoho CRM: Fetching {module} with page_token: {page_token}")

        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code != 200:
            self.logger.error(f"Zoho CRM API error: {response.status_code} - {response.text}")
            raise Exception(f"Zoho CRM API error: {response.status_code} - {response.text}")

        return response.json()


def get_rows(
    client: ZohoCRMClient,
    module: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    incremental_field_name: str,
    logger: FilteringBoundLogger,
):
    """
    Generator that yields records from Zoho CRM module.

    Args:
        client: ZohoCRMClient instance
        module: Module name to fetch
        should_use_incremental_field: Whether to use incremental sync
        db_incremental_field_last_value: Last synced value for incremental field
        incremental_field_name: Name of the field to use for incremental sync
        logger: Logger instance

    Yields:
        List of records from the API
    """
    page = 1
    has_more = True
    page_token = None

    # Parse the last value if it's a datetime string
    modified_since = None
    if should_use_incremental_field and db_incremental_field_last_value:
        try:
            if isinstance(db_incremental_field_last_value, str):
                modified_since = datetime.fromisoformat(db_incremental_field_last_value.replace("Z", "+00:00"))
            elif isinstance(db_incremental_field_last_value, datetime):
                modified_since = db_incremental_field_last_value
        except Exception as e:
            logger.warning(f"Could not parse incremental field value: {e}")

    while has_more:
        try:
            # For the first 2000 records, use page-based pagination
            # For more than 2000, we need to use page_token
            if page == 1 and not page_token:
                response = client.get_records(
                    module=module,
                    page=page,
                    per_page=200,
                    sort_by=incremental_field_name,
                    sort_order="asc",
                    modified_since=modified_since,
                )
            else:
                # Use page token for subsequent pages
                response = client.get_records_with_page_token(
                    module=module,
                    page_token=page_token,
                    per_page=200,
                    sort_by=incremental_field_name,
                    sort_order="asc",
                )

            # Extract data
            data = response.get("data", [])
            info = response.get("info", {})

            if data:
                logger.debug(f"Zoho CRM: Fetched {len(data)} records from {module}, page {page}")
                yield data

            # Check if there are more pages
            has_more = info.get("more_records", False)
            page_token = info.get("next_page_token")

            if not has_more:
                break

            page += 1

        except Exception:
            logger.exception("Error fetching Zoho CRM records")
            raise


def zoho_crm_source(
    access_token: str,
    api_domain: str,
    module: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """
    Create a SourceResponse for Zoho CRM data.

    Args:
        access_token: OAuth access token
        api_domain: Zoho API domain
        module: Module name to sync
        should_use_incremental_field: Whether to use incremental sync
        db_incremental_field_last_value: Last synced value
        logger: Logger instance

    Returns:
        SourceResponse configured for the Zoho CRM module
    """
    client = ZohoCRMClient(access_token=access_token, api_domain=api_domain, logger=logger)

    # Get the incremental field config for this module
    incremental_field_config = INCREMENTAL_FIELDS.get(module, [])
    # Default to Modified_Time for incremental sync as it's more reliable
    incremental_field_name = (
        incremental_field_config[1]["field"] if len(incremental_field_config) > 1 else "Modified_Time"
    )

    return SourceResponse(
        items=lambda: get_rows(
            client=client,
            module=module,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field_name=incremental_field_name,
            logger=logger,
        ),
        primary_keys=["id"],
        name=module,
        # Zoho CRM returns data in ascending order when sorted
        sort_mode="asc",
        # Use datetime partitioning on Created_Time for efficient merging
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["Created_Time"],
    )


def validate_credentials(access_token: str, api_domain: str) -> bool:
    """
    Validate Zoho CRM credentials by making a test API call.

    Args:
        access_token: OAuth access token
        api_domain: Zoho API domain

    Returns:
        True if credentials are valid, False otherwise
    """
    url = f"{api_domain}/crm/v6/settings/modules"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers)
        return response.status_code == 200
    except Exception:
        return False
