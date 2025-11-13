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
    MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS,
    MAX_TIKTOK_DAYS_TO_QUERY,
    EndpointType,
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
    def _normalize_secondary_goal_fields(report: dict[str, Any]) -> None:
        """Convert TikTok's '-' placeholder values to None for secondary goal metrics."""
        secondary_goal_fields = [
            "secondary_goal_result",
            "cost_per_secondary_goal_result",
            "secondary_goal_result_rate",
        ]

        for field in secondary_goal_fields:
            if field in report and report[field] == "-":
                report[field] = None

    @staticmethod
    def transform_analytics_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Standardize analytics reports for consistent data structure.

        Applies analytics-specific transformations:
        - Merges metrics and dimensions into flat structure
        - Normalizes placeholder values for secondary goal metrics
        - Handles both structured reports (with dimensions/metrics) and flat reports
        """
        processed_reports = []
        for report in reports:
            if "metrics" in report and "dimensions" in report:
                merged_report = {**report["metrics"], **report["dimensions"]}
                TikTokReportResource._normalize_secondary_goal_fields(merged_report)
                processed_reports.append(merged_report)
            else:
                processed_reports.append(report)

        return processed_reports

    @staticmethod
    def _normalize_entity_status(report: dict[str, Any]) -> None:
        """Set default status for entities that don't have explicit status differentiation."""
        if "current_status" not in report:
            report["current_status"] = "ACTIVE"

    @staticmethod
    def _normalize_timestamps(report: dict[str, Any]) -> None:
        """Ensure modify_time exists by using create_time as fallback."""
        if "modify_time" not in report and "create_time" in report:
            report["modify_time"] = report["create_time"]

    @staticmethod
    def _convert_comment_settings(report: dict[str, Any]) -> None:
        """Convert comment disable flag from integer to boolean representation."""
        if "is_comment_disable" in report:
            report["is_comment_disable"] = report["is_comment_disable"] == 0

    @staticmethod
    def transform_entity_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Standardize entity reports (campaigns, ad groups, ads) for consistent data structure.

        Applies common transformations:
        - Sets default entity status
        - Normalizes timestamp fields
        - Converts boolean flags
        """
        processed_reports = []
        for report in reports:
            normalized_report = report.copy()

            TikTokReportResource._normalize_entity_status(normalized_report)
            TikTokReportResource._normalize_timestamps(normalized_report)
            TikTokReportResource._convert_comment_settings(normalized_report)

            processed_reports.append(normalized_report)

        return processed_reports

    @staticmethod
    def _convert_timestamp_to_datetime(report: dict[str, Any]) -> None:
        """Convert Unix timestamp to timezone-aware datetime object."""
        if "create_time" in report and isinstance(report["create_time"], int | float):
            report["create_time"] = datetime.fromtimestamp(report["create_time"], tz=UTC)

    @staticmethod
    def transform_account_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Standardize advertiser account reports for consistent data structure.

        Applies account-specific transformations:
        - Converts Unix timestamps to datetime objects
        """
        processed_reports = []
        for report in reports:
            normalized_report = report.copy()

            TikTokReportResource._convert_timestamp_to_datetime(normalized_report)

            processed_reports.append(normalized_report)

        return processed_reports

    @classmethod
    def apply_stream_transformations(cls, endpoint_type: EndpointType, reports: Iterable[Any]) -> list[dict[str, Any]]:
        """
        Apply appropriate transformations based on the endpoint type.

        Routes reports to the correct transformation method based on endpoint category.
        """
        reports_list = list(reports)

        match endpoint_type:
            case EndpointType.REPORT:
                return cls.transform_analytics_reports(reports_list)
            case EndpointType.ENTITY:
                return cls.transform_entity_reports(reports_list)
            case EndpointType.ACCOUNT:
                return cls.transform_account_reports(reports_list)
            case _:
                raise ValueError(f"Endpoint type: {endpoint_type} is not implemented")

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
