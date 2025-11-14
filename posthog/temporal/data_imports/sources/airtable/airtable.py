"""Airtable API client implementation"""

import time
from typing import Any, Iterator
from collections.abc import Callable

import requests
from structlog.typing import FilteringBoundLogger

from posthog.temporal.data_imports.sources.airtable.settings import (
    AIRTABLE_API_URL,
    PAGE_SIZE,
    RATE_LIMIT_PERIOD,
    RATE_LIMIT_REQUESTS,
)


class AirtableAPIError(Exception):
    """Raised when Airtable API returns an error"""

    pass


class AirtableRateLimiter:
    """Simple rate limiter for Airtable API (5 requests per second)"""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, period: float = RATE_LIMIT_PERIOD):
        self.max_requests = max_requests
        self.period = period
        self.requests: list[float] = []

    def wait_if_needed(self) -> None:
        """Wait if we've exceeded the rate limit"""
        now = time.time()
        self.requests = [req_time for req_time in self.requests if now - req_time < self.period]

        if len(self.requests) >= self.max_requests:
            sleep_time = self.period - (now - self.requests[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.requests = []

        self.requests.append(time.time())


def list_bases(access_token: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    """
    List all accessible bases for the given access token.

    Args:
        access_token: Airtable Personal Access Token
        logger: Logger instance

    Returns:
        List of base objects with id, name, and permission level
    """
    url = f"{AIRTABLE_API_URL}/meta/bases"
    headers = {"Authorization": f"Bearer {access_token}"}

    logger.info(f"Fetching bases from {url}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        bases = data.get("bases", [])
        logger.info(f"Found {len(bases)} bases")
        return bases
    except requests.exceptions.RequestException as e:
        logger.error(f"Error listing bases: {e}")
        raise AirtableAPIError(f"Failed to list bases: {e}") from e


def list_tables(base_id: str, access_token: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    """
    List all tables in a given base.

    Args:
        base_id: Airtable base ID (e.g., 'appXXXXXXXXXXXXXX')
        access_token: Airtable Personal Access Token
        logger: Logger instance

    Returns:
        List of table objects with id, name, fields, and views
    """
    url = f"{AIRTABLE_API_URL}/meta/bases/{base_id}/tables"
    headers = {"Authorization": f"Bearer {access_token}"}

    logger.info(f"Fetching tables from base {base_id}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        tables = data.get("tables", [])
        logger.info(f"Found {len(tables)} tables in base {base_id}")
        return tables
    except requests.exceptions.RequestException as e:
        logger.error(f"Error listing tables: {e}")
        raise AirtableAPIError(f"Failed to list tables for base {base_id}: {e}") from e


def fetch_records(
    base_id: str,
    table_id: str,
    access_token: str,
    logger: FilteringBoundLogger,
    incremental_field_last_value: str | None = None,
    rate_limiter: AirtableRateLimiter | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """
    Fetch records from an Airtable table with pagination support.

    Args:
        base_id: Airtable base ID
        table_id: Airtable table ID or name
        access_token: Airtable Personal Access Token
        logger: Logger instance
        incremental_field_last_value: Last value for incremental sync (ISO format datetime)
        rate_limiter: Optional rate limiter instance

    Yields:
        Lists of record dictionaries
    """
    if rate_limiter is None:
        rate_limiter = AirtableRateLimiter()

    url = f"{AIRTABLE_API_URL}/{base_id}/{table_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    params: dict[str, Any] = {"pageSize": PAGE_SIZE}

    if incremental_field_last_value:
        formula = f"{{createdTime}} > '{incremental_field_last_value}'"
        params["filterByFormula"] = formula
        params["sort[0][field]"] = "createdTime"
        params["sort[0][direction]"] = "asc"
        logger.info(f"Using incremental sync with filter: {formula}")

    offset = None
    total_records = 0

    while True:
        rate_limiter.wait_if_needed()

        if offset:
            params["offset"] = offset

        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            records = data.get("records", [])
            if records:
                total_records += len(records)
                logger.info(f"Fetched {len(records)} records (total: {total_records})")
                yield records

            offset = data.get("offset")
            if not offset:
                logger.info(f"Finished fetching records. Total: {total_records}")
                break

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching records: {e}")
            raise AirtableAPIError(f"Failed to fetch records from {base_id}/{table_id}: {e}") from e


def validate_credentials(access_token: str, logger: FilteringBoundLogger) -> bool:
    """
    Validate Airtable credentials by attempting to list bases.

    Args:
        access_token: Airtable Personal Access Token
        logger: Logger instance

    Returns:
        True if credentials are valid, False otherwise
    """
    try:
        bases = list_bases(access_token, logger)
        return len(bases) >= 0
    except Exception as e:
        logger.error(f"Credential validation failed: {e}")
        return False


def airtable_source(
    access_token: str,
    base_id: str,
    table_id: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """
    Main source function that yields records from an Airtable table.

    Args:
        access_token: Airtable Personal Access Token
        base_id: Airtable base ID
        table_id: Airtable table ID or name
        logger: Logger instance
        should_use_incremental_field: Whether to use incremental sync
        db_incremental_field_last_value: Last synced value for incremental field

    Yields:
        Lists of record dictionaries
    """
    rate_limiter = AirtableRateLimiter()

    incremental_value = db_incremental_field_last_value if should_use_incremental_field else None

    logger.info(
        f"Starting Airtable sync for base={base_id}, table={table_id}, "
        f"incremental={should_use_incremental_field}, last_value={incremental_value}"
    )

    yield from fetch_records(
        base_id=base_id,
        table_id=table_id,
        access_token=access_token,
        logger=logger,
        incremental_field_last_value=incremental_value,
        rate_limiter=rate_limiter,
    )
