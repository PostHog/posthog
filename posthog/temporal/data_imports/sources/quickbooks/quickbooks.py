import time
from typing import Any, Optional
from datetime import datetime

import requests
import structlog
from requests.auth import HTTPBasicAuth

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.models import ExternalDataJob

logger = structlog.get_logger(__name__)

API_BASE_URL = "https://quickbooks.api.intuit.com/v3/company"
API_VERSION = "v3"


class QuickBooksPermissionError(Exception):
    """Raised when QuickBooks API returns permission errors."""

    def __init__(self, message: str, missing_permissions: dict[str, list[str]]):
        super().__init__(message)
        self.missing_permissions = missing_permissions


def validate_credentials(access_token: str, realm_id: str) -> bool:
    """Validate QuickBooks credentials by making a test API call."""
    try:
        url = f"{API_BASE_URL}/{realm_id}/companyinfo/{realm_id}"
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            return False
        else:
            logger.warning(f"Unexpected status code when validating credentials: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error validating QuickBooks credentials: {str(e)}")
        raise


def _make_request(
    access_token: str,
    realm_id: str,
    endpoint: str,
    params: Optional[dict[str, Any]] = None,
    logger_: Optional[FilteringBoundLogger] = None,
) -> dict[str, Any]:
    """Make a request to the QuickBooks API."""
    url = f"{API_BASE_URL}/{realm_id}/query"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    # Build the SQL query for QuickBooks
    query = f"SELECT * FROM {endpoint}"

    if params:
        where_clauses = []
        if "updated_since" in params and params["updated_since"]:
            # Format datetime for QuickBooks query
            where_clauses.append(f"MetaData.LastUpdatedTime >= '{params['updated_since']}'")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Add ordering for incremental sync
        query += " ORDER BY MetaData.LastUpdatedTime ASC"

        # Add pagination
        if "start_position" in params:
            query += f" STARTPOSITION {params['start_position']}"

        if "max_results" in params:
            query += f" MAXRESULTS {params['max_results']}"

    request_params = {"query": query}

    if logger_:
        logger_.debug(f"Making QuickBooks API request", endpoint=endpoint, query=query)

    try:
        response = requests.get(url, headers=headers, params=request_params, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise QuickBooksPermissionError(
                "Unauthorized: Invalid or expired access token",
                {"authentication": ["Access token is invalid or expired"]},
            )
        elif e.response.status_code == 403:
            raise QuickBooksPermissionError(
                f"Forbidden: Insufficient permissions for {endpoint}",
                {endpoint: ["Read permission required"]},
            )
        else:
            logger.error(f"QuickBooks API error: {e.response.status_code} - {e.response.text}")
            raise
    except Exception as e:
        logger.error(f"Error making QuickBooks API request: {str(e)}")
        raise


def quickbooks_source(
    access_token: str,
    realm_id: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    db_incremental_field_earliest_value: Any,
    logger: FilteringBoundLogger,
    job: Optional[ExternalDataJob] = None,
) -> SourceResponse:
    """
    Create a QuickBooks data source.

    Args:
        access_token: OAuth access token for QuickBooks API
        realm_id: QuickBooks company/realm ID
        endpoint: The QuickBooks entity to sync (e.g., "Invoice", "Customer")
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last synced timestamp for incremental sync
        db_incremental_field_earliest_value: Earliest synced timestamp
        logger: Logger instance
        job: External data job for tracking

    Returns:
        SourceResponse with QuickBooks data
    """

    def _get_data():
        """Generator that yields QuickBooks data."""
        start_position = 1
        max_results = 1000  # QuickBooks max is 1000 per request

        params: dict[str, Any] = {
            "max_results": max_results,
        }

        # Add incremental filter if enabled
        if should_use_incremental_field and db_incremental_field_last_value:
            # Convert timestamp to QuickBooks format (ISO 8601)
            if isinstance(db_incremental_field_last_value, (int, float)):
                updated_since = datetime.fromtimestamp(db_incremental_field_last_value).isoformat()
            else:
                updated_since = str(db_incremental_field_last_value)

            params["updated_since"] = updated_since
            logger.debug(
                f"Using incremental sync for {endpoint}",
                updated_since=updated_since,
            )

        while True:
            params["start_position"] = start_position

            try:
                response = _make_request(access_token, realm_id, endpoint, params, logger)

                # Extract the query response
                query_response = response.get("QueryResponse", {})
                items = query_response.get(endpoint, [])

                if not items:
                    logger.debug(f"No more items found for {endpoint}")
                    break

                logger.debug(f"Fetched {len(items)} items from {endpoint}")

                # Yield items as a list of dicts
                yield items

                # Check if there are more results
                # QuickBooks returns maxResults items if there might be more
                if len(items) < max_results:
                    break

                start_position += len(items)

                # Rate limiting - QuickBooks has rate limits
                time.sleep(0.1)

            except QuickBooksPermissionError:
                raise
            except Exception as e:
                logger.error(f"Error fetching data from {endpoint}: {str(e)}")
                raise

    return SourceResponse(
        items=_get_data(),
        primary_keys=["Id"],
        incremental_field="MetaData.LastUpdatedTime",
        incremental_field_type="datetime",
        partition_keys=["Id"],
        partition_mode="numerical",
        partition_size=5000,
    )
