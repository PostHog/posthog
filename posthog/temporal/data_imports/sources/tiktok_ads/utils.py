import copy
from datetime import date, datetime, timedelta
from typing import Any, Optional

import structlog
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.auth import AuthConfigBase
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from requests import PreparedRequest

from posthog.temporal.data_imports.sources.tiktok_ads.settings import (
    MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS,
    MAX_TIKTOK_DAYS_TO_QUERY,
    TIKTOK_ADS_CONFIG,
)

logger = structlog.get_logger(__name__)


def flatten_tiktok_report_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten TikTok's nested report structure.

    TikTok returns reports with nested structure:
    {
        "dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"},
        "metrics": {"clicks": "947", "impressions": "23241"}
    }

    We flatten it to:
    {
        "campaign_id": "123",
        "stat_time_day": "2025-09-27",
        "clicks": "947",
        "impressions": "23241"
    }
    """
    if isinstance(record, dict) and "metrics" in record and "dimensions" in record:
        flattened = {}
        flattened.update(record.get("dimensions", {}))
        flattened.update(record.get("metrics", {}))
        return flattened
    else:
        return record


def flatten_tiktok_reports(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transform TikTok report data by flattening nested structure."""
    return [flatten_tiktok_report_record(item) for item in items]


def get_incremental_date_range(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any] = None
) -> tuple[str, str]:
    """Calculate date range for incremental sync based on last synced value."""
    ends_at = datetime.now().strftime("%Y-%m-%d")

    if should_use_incremental_field and db_incremental_field_last_value:
        try:
            if isinstance(db_incremental_field_last_value, datetime):
                last_datetime = db_incremental_field_last_value
            elif isinstance(db_incremental_field_last_value, date):
                last_datetime = datetime.combine(db_incremental_field_last_value, datetime.min.time())
            elif isinstance(db_incremental_field_last_value, str):
                last_datetime = parser.parse(db_incremental_field_last_value)
            else:
                last_datetime = datetime.fromisoformat(str(db_incremental_field_last_value))

            starts_at = last_datetime.strftime("%Y-%m-%d")

        except Exception:
            starts_at = (datetime.now() - timedelta(days=MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS)).strftime("%Y-%m-%d")
    else:
        # If there isn't an incremental field last value, we fetch the last 365 days of data
        starts_at = (datetime.now() - timedelta(days=MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS)).strftime("%Y-%m-%d")

    return starts_at, ends_at


def generate_date_chunks(
    start_date: str, end_date: str, chunk_days: int = MAX_TIKTOK_DAYS_TO_QUERY
) -> list[tuple[str, str]]:
    """
    Generate date chunks that respect TikTok's 30-day limit.
    Returns list of (start_date, end_date) tuples for sequential API calls.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    chunks = []
    current_start = start_dt

    while current_start <= end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_days), end_dt)

        chunks.append((current_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))

        current_start = chunk_end + timedelta(days=1)

    return chunks


class TikTokAdsPaginator(BasePaginator):
    """TikTok Ads API paginator that extends dlt's BasePaginator"""

    def __init__(self):
        super().__init__()
        self.current_page = 1
        self._has_next_page = False
        self.total_pages = 0
        self.total_number = 0
        self.page_size = 0

    def update_state(self, response: Response, data: Optional[Any] = None) -> None:
        """Update pagination state from TikTok API response."""
        try:
            json_data = response.json()
            api_code = json_data.get("code", -1)

            if api_code == 0:
                page_info = json_data.get("data", {}).get("page_info", {})

                self.total_pages = page_info.get("total_page", 0)
                self.total_number = page_info.get("total_number", 0)
                self.page_size = page_info.get("page_size", 0)
                current_page = page_info.get("page", 1)

                self._has_next_page = current_page < self.total_pages

                if self._has_next_page:
                    self.current_page = current_page + 1
            else:
                self._has_next_page = False
                logger.warning(
                    "tiktok_ads_api_error",
                    api_code=api_code,
                    message=json_data.get("message", "Unknown API error"),
                )
        except Exception as e:
            self._has_next_page = False
            logger.exception("tiktok_ads_paginator_error", error=str(e))

    def update_request(self, request: Request) -> None:
        """Update the request with pagination parameters."""
        if request.params is None:
            request.params = {}
        request.params["page"] = self.current_page


def is_report_endpoint(endpoint_name: str) -> bool:
    """Check if an endpoint is a report endpoint based on its configuration."""
    if endpoint_name not in TIKTOK_ADS_CONFIG:
        return False

    endpoint_config = TIKTOK_ADS_CONFIG[endpoint_name]
    endpoint = endpoint_config.resource.get("endpoint")
    if isinstance(endpoint, dict):
        incremental = endpoint.get("incremental")
        if isinstance(incremental, dict):
            return incremental.get("cursor_path") == "stat_time_day"
    return False


class TikTokAdsAuth(AuthConfigBase):
    """
    TikTok Ads API authentication handler for dlt REST client.

    TikTok requires a custom 'Access-Token' header instead of the standard
    'Authorization: Bearer' pattern, so we can't use dlt's built-in BearerTokenAuth.
    """

    def __init__(self, access_token: str):
        super().__init__()
        self.access_token = access_token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        """Add TikTok Ads authentication headers to the request."""
        request.headers["Access-Token"] = self.access_token
        request.headers["Content-Type"] = "application/json"

        return request


def create_date_chunked_resources(
    base_resource_config: dict,
    start_date: str,
    end_date: str,
    advertiser_id: str,
    chunk_days: int = MAX_TIKTOK_DAYS_TO_QUERY,
) -> list[dict]:
    """
    Create multiple resources for date chunking with rest_api_resources.
    Each chunk becomes a separate resource that can be processed in parallel.
    """
    date_chunks = generate_date_chunks(start_date, end_date, chunk_days)
    resources = []

    for i, (chunk_start, chunk_end) in enumerate(date_chunks):
        # Create a deep copy of the base resource config
        resource_config = copy.deepcopy(base_resource_config)

        # Update the resource name to be unique for each chunk
        resource_name = f"{base_resource_config['name']}_chunk_{i}"
        resource_config["name"] = resource_name
        resource_config["table_name"] = base_resource_config.get("table_name", base_resource_config["name"])

        # Update endpoint params with date range and advertiser_id
        endpoint = resource_config["endpoint"]
        params = endpoint.get("params", {})

        # Replace template variables in params
        params = {
            key: value.format(advertiser_id=advertiser_id, start_date=chunk_start, end_date=chunk_end)
            if isinstance(value, str)
            else value
            for key, value in params.items()
        }

        endpoint["params"] = params

        # For date chunking, we handle incremental manually by setting start_date and end_date
        if "incremental" in endpoint:
            del endpoint["incremental"]

        resource_config["endpoint"] = endpoint
        resources.append(resource_config)

    return resources
