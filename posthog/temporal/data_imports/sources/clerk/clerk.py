"""Clerk API source implementation"""

from typing import Any, Iterator, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.clerk.settings import INCREMENTAL_FIELDS

DEFAULT_LIMIT = 100


def get_clerk_rows(
    api_key: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
) -> Iterator[dict]:
    """
    Fetch rows from Clerk API endpoints.

    Args:
        api_key: Clerk secret key
        endpoint: The endpoint to fetch (users, sessions, etc.)
        db_incremental_field_last_value: Last synced value for incremental field
        logger: Logger instance
        should_use_incremental_field: Whether to use incremental syncing

    Yields:
        Dictionary records from the API
    """
    base_url = "https://api.clerk.com/v1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Get incremental field config
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created_at"

    offset = 0
    limit = DEFAULT_LIMIT

    while True:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        # Add ordering for consistent pagination
        params["order_by"] = f"{incremental_field_name}"

        # Add incremental filtering if applicable
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # Clerk uses Unix timestamps in milliseconds
            if isinstance(db_incremental_field_last_value, (int, float)):
                # Convert to milliseconds if needed
                timestamp_ms = int(db_incremental_field_last_value * 1000) if db_incremental_field_last_value < 10000000000 else int(db_incremental_field_last_value)
                params[f"{incremental_field_name}[gt]"] = timestamp_ms
            else:
                logger.warning(f"Unexpected type for incremental field value: {type(db_incremental_field_last_value)}")

        try:
            logger.debug(f"Fetching Clerk {endpoint} with offset {offset}")
            response = requests.get(
                f"{base_url}/{endpoint}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()

            # Clerk returns data directly as an array
            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Clerk API: {type(data)}")
                break

            if not data:
                # No more data
                break

            # Yield each record
            for record in data:
                yield record

            # If we got less than the limit, we're done
            if len(data) < limit:
                break

            offset += limit

        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching Clerk {endpoint}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching Clerk {endpoint}: {e}")
            raise


def validate_clerk_credentials(api_key: str) -> bool:
    """
    Validate Clerk API credentials by making a test request.

    Args:
        api_key: Clerk secret key

    Returns:
        True if credentials are valid, False otherwise
    """
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Try to fetch a small number of users to validate credentials
        response = requests.get(
            "https://api.clerk.com/v1/users",
            headers=headers,
            params={"limit": 1},
        )
        response.raise_for_status()
        return True
    except requests.HTTPError:
        return False
    except Exception:
        return False
