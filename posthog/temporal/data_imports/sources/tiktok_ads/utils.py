import copy
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import structlog
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.auth import AuthConfigBase
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from requests import PreparedRequest
from requests.exceptions import HTTPError, RequestException, Timeout

from posthog.temporal.data_imports.sources.tiktok_ads.settings import (
    ENDPOINT_AD_MANAGEMENT,
    ENDPOINT_ADVERTISERS,
    ENDPOINT_INSIGHTS,
    MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS,
    MAX_TIKTOK_DAYS_TO_QUERY,
)

logger = structlog.get_logger(__name__)


class TikTokAdsAPIError(Exception):
    """Custom exception for TikTok Ads API errors that should trigger retries."""

    def __init__(self, message: str, api_code: int | None = None, response: Optional[Response] = None):
        super().__init__(message)
        self.api_code = api_code
        self.response = response


class TikTokErrorHandler:
    """Centralized error handling for TikTok API."""

    @staticmethod
    def is_retryable(exception: Exception) -> bool:
        """
        Determine if a TikTok API exception should be retried.

        TikTok has specific rate limits and error codes that should trigger retries:
        - QPM limit: need to wait 5 minutes before making API requests again
        - QPD limit: need to wait until the next day (UTC+0 time) to make API requests again
        - Note that the QPD limit resets at 00:00:00 UTC+0 time every day

        https://business-api.tiktok.com/portal/docs?id=1740029171730433
        """
        if isinstance(exception, TikTokAdsAPIError):
            return True

        if isinstance(exception, HTTPError) and hasattr(exception, "response") and exception.response is not None:
            status_code = exception.response.status_code
            return status_code in [429, 500, 502, 503, 504]

        if isinstance(exception, Timeout | RequestException):
            return True

        return False


class TikTokDateRangeManager:
    """Handles date range calculations and chunking for TikTok API requests."""

    @staticmethod
    def get_incremental_range(
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
            starts_at = (datetime.now() - timedelta(days=MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS)).strftime("%Y-%m-%d")

        return starts_at, ends_at

    @staticmethod
    def generate_chunks(
        start_date: str, end_date: str, chunk_days: int = MAX_TIKTOK_DAYS_TO_QUERY
    ) -> list[tuple[str, str]]:
        """
        Generate date chunks that respect TikTok's 29-day limit.
        Returns list of (start_date, end_date) tuples for sequential API calls.
        """
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        chunks = []
        current_start = start_dt

        while current_start <= end_dt:
            chunk_end = current_start + timedelta(days=chunk_days - 1)

            if chunk_end > end_dt:
                chunk_end = end_dt

            chunks.append((current_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))

            current_start = chunk_end + timedelta(days=1)

        return chunks


class TikTokReportResource:
    """Handles report-specific operations like flattening and date chunking."""

    @staticmethod
    def transform_insights_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Transform TikTok insights records.

        Reference: https://github.com/singer-io/tap-tiktok-ads/blob/master/tap_tiktok_ads/streams.py
        """
        transformed_records = []
        for record in records:
            if "metrics" in record and "dimensions" in record:
                # Merging of 2 dicts by not using '|' for older python version compatibility
                transformed_record = {**record["metrics"], **record["dimensions"]}

                # Handle TikTok's '-' values for specific fields
                if "secondary_goal_result" in transformed_record and transformed_record["secondary_goal_result"] == "-":
                    transformed_record["secondary_goal_result"] = None
                if (
                    "cost_per_secondary_goal_result" in transformed_record
                    and transformed_record["cost_per_secondary_goal_result"] == "-"
                ):
                    transformed_record["cost_per_secondary_goal_result"] = None
                if (
                    "secondary_goal_result_rate" in transformed_record
                    and transformed_record["secondary_goal_result_rate"] == "-"
                ):
                    transformed_record["secondary_goal_result_rate"] = None

                transformed_records.append(transformed_record)
        return transformed_records

    @staticmethod
    def transform_management_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Transform TikTok management records.

        Reference: https://github.com/singer-io/tap-tiktok-ads/blob/master/tap_tiktok_ads/streams.py
        """
        transformed_records = []
        for record in records:
            # Setting the custom 'current_status' as 'ACTIVE', TikTok does not differentiate between ACTIVE/DELETE records in response.
            if "current_status" not in record:
                record["current_status"] = "ACTIVE"

            # Handle missing modify_time - use create_time as fallback
            if "modify_time" not in record and "create_time" in record:
                record["modify_time"] = record["create_time"]

            # In case of an adgroup request, transform 'is_comment_disabled' type from integer to boolean
            if "is_comment_disable" in record:
                record["is_comment_disable"] = bool(record["is_comment_disable"] == 0)

            transformed_records.append(record)
        return transformed_records

    @staticmethod
    def transform_advertisers_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Transform TikTok advertisers records.

        Reference: https://github.com/singer-io/tap-tiktok-ads/blob/master/tap_tiktok_ads/streams.py
        """
        transformed_records = []
        for record in records:
            # Convert timestamp to datetime with timezone
            if "create_time" in record and isinstance(record["create_time"], int | float):
                record["create_time"] = datetime.fromtimestamp(record["create_time"], tz=UTC)

            transformed_records.append(record)
        return transformed_records

    @classmethod
    def pre_transform(cls, stream_name: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Transform records for every stream before writing to output as per stream category.

        Reference: https://github.com/singer-io/tap-tiktok-ads/blob/master/tap_tiktok_ads/streams.py
        """
        if stream_name in ENDPOINT_INSIGHTS:
            return cls.transform_insights_records(records)
        elif stream_name in ENDPOINT_AD_MANAGEMENT:
            return cls.transform_management_records(records)
        elif stream_name in ENDPOINT_ADVERTISERS:
            return cls.transform_advertisers_records(records)
        else:
            return records

    @classmethod
    def create_chunked_resources(
        cls,
        base_resource_config: dict,
        start_date: str,
        end_date: str,
        advertiser_id: str,
        chunk_days: int = MAX_TIKTOK_DAYS_TO_QUERY,
    ) -> list[dict]:
        """
        Create multiple resources for date chunking with rest_api_resources.
        Each chunk becomes a separate resource.
        """
        date_chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)
        resources = []

        for i, (chunk_start, chunk_end) in enumerate(date_chunks):
            resource_config = copy.deepcopy(base_resource_config)

            resource_name = f"{base_resource_config['name']}_chunk_{i}"
            resource_config["name"] = resource_name
            resource_config["table_name"] = base_resource_config.get("table_name", base_resource_config["name"])

            endpoint = resource_config["endpoint"]
            params = endpoint.get("params", {})

            params = {
                key: value.format(advertiser_id=advertiser_id, start_date=chunk_start, end_date=chunk_end)
                if isinstance(value, str)
                else value
                for key, value in params.items()
            }

            endpoint["params"] = params

            if "incremental" in endpoint:
                del endpoint["incremental"]

            resource_config["endpoint"] = endpoint
            resources.append(resource_config)

        return resources

    @classmethod
    def process_resources(cls, dlt_resources: list) -> Iterable[Any]:
        """
        Process and flatten DLT resources from report endpoints.
        Handles both single and multiple chunked resources.
        """
        result = []

        for _i, resource in enumerate(dlt_resources):
            result.extend(cls._flatten_single_resource(resource))

        return result

    @classmethod
    def _flatten_single_resource(cls, resource: Any) -> list[dict[str, Any]]:
        result = []
        for item in resource:
            if isinstance(item, list):
                result.extend(item)
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(item)
        return result

    @classmethod
    def setup_report_resources(
        cls,
        base_resource_config: dict,
        advertiser_id: str,
        should_use_incremental_field: bool,
        db_incremental_field_last_value: Optional[Any],
    ) -> list[dict]:
        """
        Setup report resources with proper date chunking.
        Calculates date ranges and creates chunked resources.
        """
        starts_at, ends_at = TikTokDateRangeManager.get_incremental_range(
            should_use_incremental_field, db_incremental_field_last_value
        )

        if not should_use_incremental_field:
            ends_at = datetime.now().strftime("%Y-%m-%d")
            starts_at = (datetime.now() - timedelta(days=MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS)).strftime("%Y-%m-%d")

        return cls.create_chunked_resources(base_resource_config, starts_at, ends_at, advertiser_id)


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
                error_message = json_data.get("message", "Unknown API error")
                logger.error(
                    "tiktok_ads_api_error",
                    api_code=api_code,
                    message=error_message,
                    response_status=response.status_code,
                )

                # https://business-api.tiktok.com/portal/docs?rid=xmtaqatxqj8&id=1737172488964097
                retryable_codes = [
                    40016,  # Requests made too frequently
                    40100,  # Requests made too frequently
                    40101,  # Requests made too frequently
                    40102,  # Requests made too frequently for a certain field value.
                    40200,  # Task error
                    40201,  # Task is not ready
                    40202,  # Write or update entity conflict
                    40700,  # Internal service validation error
                    50000,  # System error
                    50002,  # Error processing request on TikTok side. Please see error message for details.
                    51305,  # Satellite service error
                    60001,  # The system is in maintenance.
                ]

                if api_code in retryable_codes:
                    raise TikTokAdsAPIError(
                        f"TikTok API error: {error_message} (code: {api_code})", api_code=api_code, response=response
                    )
                else:
                    raise ValueError(f"TikTok API client error (non-retryable): {error_message} (code: {api_code})")
        except TikTokAdsAPIError:
            raise
        except ValueError:
            raise
        except Exception as e:
            self._has_next_page = False
            logger.exception("tiktok_ads_paginator_error", error=str(e))
            raise TikTokAdsAPIError(f"Failed to parse TikTok API response: {str(e)}", response=response)

    def update_request(self, request: Request) -> None:
        """Update the request with pagination parameters."""
        if request.params is None:
            request.params = {}
        request.params["page"] = self.current_page


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
