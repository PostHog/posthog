"""Polar.sh API integration for data warehouse imports"""

import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.polar.settings import INCREMENTAL_FIELDS

# Polar API base URLs
POLAR_API_URL = "https://api.polar.sh/v1"
DEFAULT_LIMIT = 100


@dataclasses.dataclass
class PolarPaginationState:
    """Tracks pagination state for Polar API"""

    page: int = 1
    has_more: bool = True


def validate_credentials(access_token: str) -> bool:
    """
    Validate Polar access token by making a test API call.

    Args:
        access_token: Polar Organization Access Token

    Returns:
        bool: True if credentials are valid, False otherwise
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(f"{POLAR_API_URL}/products", headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_polar_data(
    access_token: str,
    endpoint: str,
    organization_id: str | None,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """
    Fetch data from Polar API with pagination support.

    Args:
        access_token: Polar Organization Access Token
        endpoint: The resource endpoint to fetch (e.g., 'orders', 'subscriptions')
        organization_id: Optional organization ID to filter by
        db_incremental_field_last_value: Last value of incremental field for incremental syncs
        logger: Logger instance

    Yields:
        List of dictionaries containing the fetched data
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    pagination_state = PolarPaginationState()

    while pagination_state.has_more:
        params: dict[str, Any] = {
            "limit": DEFAULT_LIMIT,
            "page": pagination_state.page,
        }

        # Add organization filter if provided
        if organization_id:
            params["organization_id"] = organization_id

        # Add incremental filter if we have a last value
        if db_incremental_field_last_value:
            incremental_field = INCREMENTAL_FIELDS.get(endpoint, [])
            if incremental_field:
                field_name = incremental_field[0]["field"]
                # For datetime fields, we need to filter for records created after the last sync
                params[f"{field_name}[gte]"] = db_incremental_field_last_value

        try:
            logger.info(f"Fetching {endpoint} from Polar API", page=pagination_state.page, params=params)
            response = requests.get(
                f"{POLAR_API_URL}/{endpoint}",
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()

            # Polar API uses pagination with 'items' and 'pagination' structure
            items = data.get("items", [])

            if not items:
                pagination_state.has_more = False
                break

            yield items

            # Check if there are more pages
            pagination = data.get("pagination", {})
            total_count = pagination.get("total_count", 0)
            current_count = pagination_state.page * DEFAULT_LIMIT

            if current_count >= total_count:
                pagination_state.has_more = False
            else:
                pagination_state.page += 1

        except requests.exceptions.HTTPError as e:
            logger.exception(
                f"HTTP error fetching {endpoint} from Polar API", error=str(e), status_code=e.response.status_code
            )
            raise
        except Exception as e:
            logger.exception(f"Error fetching {endpoint} from Polar API", error=str(e))
            raise


def polar_source(
    access_token: str,
    endpoint: str,
    organization_id: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """
    Create a Polar data source for the pipeline.

    Args:
        access_token: Polar Organization Access Token
        endpoint: The resource endpoint to fetch
        organization_id: Optional organization ID to filter by
        should_use_incremental_field: Whether to use incremental syncing
        db_incremental_field_last_value: Last value of incremental field
        logger: Logger instance

    Returns:
        SourceResponse containing the data iterator and metadata
    """
    incremental_value = db_incremental_field_last_value if should_use_incremental_field else None

    items = get_polar_data(
        access_token=access_token,
        endpoint=endpoint,
        organization_id=organization_id,
        db_incremental_field_last_value=incremental_value,
        logger=logger,
    )

    incremental_field_info = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field = incremental_field_info[0]["field"] if incremental_field_info else None

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        incremental_field=incremental_field,
        partition_keys=["created_at"] if incremental_field == "created_at" else None,
        partition_mode="datetime",
        partition_format=None,
    )
