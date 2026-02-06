import copy
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any, Optional

import structlog
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from requests.exceptions import HTTPError, RequestException, Timeout

from posthog.temporal.data_imports.sources.snapchat_ads.settings import MAX_SNAPCHAT_DAYS_TO_QUERY, EndpointType

logger = structlog.get_logger(__name__)

SNAPCHAT_DATE_FORMAT = "%Y-%m-%dT00:00:00"

# HTTP status codes that should trigger a retry
# https://developers.snap.com/api/marketing-api/Ads-API/errors
RETRYABLE_STATUS_CODES = [429, 500, 503]


class SnapchatAdsAPIError(Exception):
    """Custom exception for Snapchat Ads API errors that should trigger retries."""

    def __init__(self, message: str, error_code: str | None = None, response: Optional[Response] = None):
        super().__init__(message)
        self.error_code = error_code
        self.response = response


class SnapchatErrorHandler:
    """Centralized error handling for Snapchat API."""

    @staticmethod
    def is_retryable(exception: Exception) -> bool:
        """Determine if exception should trigger a retry."""
        if isinstance(exception, SnapchatAdsAPIError):
            return True

        if isinstance(exception, HTTPError) and hasattr(exception, "response") and exception.response is not None:
            return exception.response.status_code in RETRYABLE_STATUS_CODES

        if isinstance(exception, Timeout | RequestException):
            return True

        return False


class SnapchatDateRangeManager:
    """Handles date range calculations and chunking for Snapchat API requests."""

    DEFAULT_LOOKBACK_DAYS = 365

    @staticmethod
    def get_incremental_range(
        should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any] = None
    ) -> tuple[str, str]:
        """Calculate date range for incremental sync based on last synced value."""
        ends_at = (datetime.now() + timedelta(days=1)).strftime(SNAPCHAT_DATE_FORMAT)

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

                starts_at = last_datetime.strftime(SNAPCHAT_DATE_FORMAT)

            except Exception:
                starts_at = (datetime.now() - timedelta(days=SnapchatDateRangeManager.DEFAULT_LOOKBACK_DAYS)).strftime(
                    SNAPCHAT_DATE_FORMAT
                )
        else:
            starts_at = (datetime.now() - timedelta(days=SnapchatDateRangeManager.DEFAULT_LOOKBACK_DAYS)).strftime(
                SNAPCHAT_DATE_FORMAT
            )

        return starts_at, ends_at

    @staticmethod
    def generate_chunks(
        start_date: str, end_date: str, chunk_days: int = MAX_SNAPCHAT_DAYS_TO_QUERY
    ) -> list[tuple[str, str]]:
        """
        Generate date chunks that respect Snapchat's 31-day limit.
        Returns list of (start_date, end_date) tuples for sequential API calls.
        """
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        chunks = []
        current_start = start_dt

        while current_start < end_dt:
            chunk_end = current_start + timedelta(days=chunk_days - 1)

            if chunk_end >= end_dt:
                chunk_end = end_dt - timedelta(days=1)

            # Snapchat requires end_time to be at the beginning of an hour
            # So we use the next day at 00:00:00 instead of 23:59:59
            chunk_end_for_api = chunk_end + timedelta(days=1)

            chunks.append(
                (
                    current_start.strftime(SNAPCHAT_DATE_FORMAT),
                    chunk_end_for_api.strftime(SNAPCHAT_DATE_FORMAT),
                )
            )

            current_start = chunk_end + timedelta(days=1)

        return chunks


class SnapchatStatsResource:
    """Handles stats-specific operations like flattening and date chunking."""

    @staticmethod
    def transform_stats_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten nested timeseries_stat structure to individual daily records.

        Handles the breakdown response format where stats are nested inside
        breakdown_stats.<breakdown_key>[].timeseries rather than directly
        in timeseries_stat.timeseries.
        """
        processed_reports = []

        for report in reports:
            timeseries_stat = report.get("timeseries_stat", report)
            breakdown_stats = timeseries_stat.get("breakdown_stats")

            if breakdown_stats:
                entities = [entity for entities in breakdown_stats.values() for entity in entities]
            else:
                entities = [timeseries_stat]

            for entity in entities:
                entity_id = entity.get("id")
                entity_type = entity.get("type")

                for ts_entry in entity.get("timeseries", []):
                    flat_record = {
                        "id": entity_id,
                        "type": entity_type,
                        "start_time": ts_entry.get("start_time"),
                        "end_time": ts_entry.get("end_time"),
                        **ts_entry.get("stats", {}),
                    }
                    processed_reports.append(flat_record)

        return processed_reports

    @staticmethod
    def transform_entity_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract inner objects from wrapped entity responses (campaign/adsquad/ad)."""
        processed_reports = []

        for report in reports:
            # Each item is wrapped: {"campaign": {...}} or {"adsquad": {...}} or {"ad": {...}}
            inner_keys = ["campaign", "adsquad", "ad"]
            for key in inner_keys:
                if key in report:
                    processed_reports.append(report[key])
                    break
            else:
                # No wrapper found, use as-is
                processed_reports.append(report)

        return processed_reports

    @classmethod
    def apply_stream_transformations(cls, endpoint_type: EndpointType, reports: Iterable[Any]) -> list[dict[str, Any]]:
        """Apply transformations based on endpoint type."""
        reports_list = list(reports)

        match endpoint_type:
            case EndpointType.STATS:
                return cls.transform_stats_reports(reports_list)
            case EndpointType.ENTITY:
                return cls.transform_entity_reports(reports_list)
            case EndpointType.ACCOUNT:
                return reports_list

    @classmethod
    def create_chunked_resources(
        cls,
        base_resource_config: dict,
        start_date: str,
        end_date: str,
        ad_account_id: str,
        chunk_days: int = MAX_SNAPCHAT_DAYS_TO_QUERY,
    ) -> list[dict]:
        """Create chunked resources for date range queries."""
        date_chunks = SnapchatDateRangeManager.generate_chunks(start_date, end_date, chunk_days)
        resources = []

        for i, (chunk_start, chunk_end) in enumerate(date_chunks):
            resource_config = copy.deepcopy(base_resource_config)

            resource_name = f"{base_resource_config['name']}_chunk_{i}"
            resource_config["name"] = resource_name
            resource_config["table_name"] = base_resource_config.get("table_name", base_resource_config["name"])

            endpoint = resource_config["endpoint"]
            params = endpoint.get("params", {})

            # Replace placeholders in params
            params = {
                key: (
                    value.format(ad_account_id=ad_account_id, start_time=chunk_start, end_time=chunk_end)
                    if isinstance(value, str)
                    else value
                )
                for key, value in params.items()
            }

            # Replace path placeholder
            endpoint["path"] = endpoint["path"].format(ad_account_id=ad_account_id)
            endpoint["params"] = params

            if "incremental" in endpoint:
                del endpoint["incremental"]

            resource_config["endpoint"] = endpoint
            resources.append(resource_config)

        return resources

    @classmethod
    def process_resources(cls, dlt_resources: list) -> Iterable[Any]:
        """
        Process and flatten DLT resources from stats endpoints.
        Handles both single and multiple chunked resources.
        """
        result = []

        for resource in dlt_resources:
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
    def setup_stats_resources(
        cls,
        base_resource_config: dict,
        ad_account_id: str,
        should_use_incremental_field: bool,
        db_incremental_field_last_value: Optional[Any],
    ) -> list[dict]:
        """
        Setup stats resources with proper date chunking.
        Calculates date ranges and creates chunked resources.
        """
        starts_at, ends_at = SnapchatDateRangeManager.get_incremental_range(
            should_use_incremental_field, db_incremental_field_last_value
        )

        return cls.create_chunked_resources(base_resource_config, starts_at, ends_at, ad_account_id)


class SnapchatAdsPaginator(BasePaginator):
    """Cursor-based paginator using next_link from paging object."""

    def __init__(self):
        super().__init__()
        self._has_next_page = False
        self._next_link: Optional[str] = None

    def update_state(self, response: Response, data: Optional[Any] = None) -> None:
        """Update pagination state from Snapchat API response."""
        try:
            json_data = response.json()
            request_status = json_data.get("request_status", "")

            if request_status == "SUCCESS":
                paging = json_data.get("paging", {})
                self._next_link = paging.get("next_link")
                self._has_next_page = bool(self._next_link)
            else:
                self._has_next_page = False
                error_message = json_data.get("debug_message", json_data.get("display_message", "Unknown API error"))
                error_code = json_data.get("error_code")

                logger.error(
                    "snapchat_ads_api_error",
                    error_code=error_code,
                    message=error_message,
                    response_status=response.status_code,
                )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise SnapchatAdsAPIError(
                        f"Snapchat API error: {error_message} (code: {error_code})",
                        error_code=error_code,
                        response=response,
                    )
                else:
                    raise ValueError(f"Snapchat API client error (non-retryable): {error_message} (code: {error_code})")

        except SnapchatAdsAPIError:
            raise
        except ValueError:
            raise
        except Exception as e:
            self._has_next_page = False
            logger.exception("snapchat_ads_paginator_error", error=str(e))
            raise SnapchatAdsAPIError(f"Failed to parse Snapchat API response: {str(e)}", response=response)

    def update_request(self, request: Request) -> None:
        """Extract cursor from next_link and add to request params."""
        if self._next_link and request.params is not None:
            # Extract cursor from next_link query params
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(self._next_link)
            query_params = parse_qs(parsed.query)
            if "cursor" in query_params:
                request.params["cursor"] = query_params["cursor"][0]
