"""Airtable API client for fetching bases, tables, and records."""

import time
from typing import Any, Iterator
from urllib.parse import urljoin

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.airtable.settings import (
    AIRTABLE_API_BASE_URL,
    AIRTABLE_METADATA_API_BASE_URL,
    PAGE_SIZE,
    REQUESTS_PER_SECOND,
)


class AirtableClient:
    """Client for interacting with Airtable's API."""

    def __init__(self, access_token: str, logger: FilteringBoundLogger):
        self.access_token = access_token
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )
        self.last_request_time = 0.0

    def _rate_limit(self):
        """Apply rate limiting to stay within Airtable's limits (5 requests per second)."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        min_interval = 1.0 / REQUESTS_PER_SECOND

        if time_since_last_request < min_interval:
            sleep_time = min_interval - time_since_last_request
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _make_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a rate-limited request to the Airtable API."""
        self._rate_limit()
        self.logger.debug(f"Airtable: making request to {url}", params=params)

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def list_bases(self) -> list[dict[str, Any]]:
        """List all bases accessible to the authenticated user."""
        url = f"{AIRTABLE_METADATA_API_BASE_URL}/bases"
        bases = []
        offset = None

        while True:
            params = {}
            if offset:
                params["offset"] = offset

            data = self._make_request(url, params)
            bases.extend(data.get("bases", []))

            offset = data.get("offset")
            if not offset:
                break

        self.logger.info(f"Airtable: found {len(bases)} bases")
        return bases

    def get_base_schema(self, base_id: str) -> dict[str, Any]:
        """Get the schema (tables and fields) for a specific base."""
        url = f"{AIRTABLE_METADATA_API_BASE_URL}/bases/{base_id}/tables"
        data = self._make_request(url)
        return data

    def list_records(
        self,
        base_id: str,
        table_id_or_name: str,
    ) -> Iterator[list[dict[str, Any]]]:
        """
        List all records from a table.

        Yields batches of records for efficient processing.
        """
        url = urljoin(f"{AIRTABLE_API_BASE_URL}/", f"{base_id}/{table_id_or_name}")
        offset = None

        while True:
            params: dict[str, Any] = {"pageSize": PAGE_SIZE}
            if offset:
                params["offset"] = offset

            data = self._make_request(url, params)
            records = data.get("records", [])

            if records:
                yield records

            offset = data.get("offset")
            if not offset:
                break


def validate_credentials(access_token: str, logger: FilteringBoundLogger) -> bool:
    """Validate Airtable credentials by attempting to list bases."""
    try:
        client = AirtableClient(access_token, logger)
        client.list_bases()
        return True
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 401:
            return False
        raise
    except Exception:
        return False


def airtable_source(
    access_token: str,
    base_id: str,
    table_name: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """
    Create a source for fetching records from an Airtable table.

    Args:
        access_token: Airtable personal access token or OAuth token
        base_id: The ID of the Airtable base
        table_name: The name of the table to sync
        logger: Logger instance

    Returns:
        SourceResponse with the table records
    """
    client = AirtableClient(access_token, logger)
    batcher = Batcher(logger=logger)

    logger.info(f"Airtable: starting sync for base {base_id}, table {table_name}")

    def items():
        for records_batch in client.list_records(base_id, table_name):
            for record in records_batch:
                # Flatten the record structure to make it easier to query
                flattened_record = {
                    "id": record.get("id"),
                    "createdTime": record.get("createdTime"),
                    **record.get("fields", {}),
                }
                batcher.batch(flattened_record)

                if batcher.should_yield():
                    yield batcher.get_table()

        # Yield any remaining records
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()

    return SourceResponse(
        items=items(),
        primary_keys=["id"],
    )
