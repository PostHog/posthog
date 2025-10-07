import copy
import time
from datetime import date, datetime, timedelta
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
    TIKTOK_ADS_CONFIG,
)

logger = structlog.get_logger(__name__)


class TikTokAdsAPIError(Exception):
    """Custom exception for TikTok Ads API errors that should trigger retries."""

    def __init__(self, message: str, api_code: int | None = None, response: Optional[Response] = None):
        super().__init__(message)
        self.api_code = api_code
        self.response = response


# https://business-api.tiktok.com/portal/docs?id=1740029171730433 For QPM limit, you need to wait 5 minutes before you can
# make API requests again. For QPD limit, you need to wait until the next day (UTC+0 time) to make API requests again.
# Note that the QPD limit resets at 00:00:00 UTC+0 time every day.
def exponential_backoff_retry(
    func,
    max_retries: int = 5,
    base_delay: float = 301.0,  # tiktok has 5 minutes circuit breaker when too many requests are made and QPM/QPD limits are exceeded
    multiplier: float = 1.68,
    exceptions: tuple = (TikTokAdsAPIError,),
):
    """
    Decorator for exponential backoff retry with custom parameters.

    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        multiplier: Exponential multiplier
        exceptions: Tuple of exceptions that should trigger a retry
    """

    def wrapper(*args, **kwargs):
        last_exception = None

        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e

                if attempt == max_retries:
                    logger.exception(
                        "tiktok_ads_max_retries_exceeded",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e),
                    )
                    raise

                # Calculate delay: base_delay * multiplier^attempt
                delay = base_delay * (multiplier**attempt)

                logger.warning(
                    "tiktok_ads_retry_attempt",
                    function=func.__name__,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    error=str(e),
                )

                time.sleep(delay)
            except HTTPError as e:
                # Handle HTTP errors - retry on rate limiting and server errors
                if hasattr(e, "response") and e.response is not None:
                    status_code = e.response.status_code
                    if status_code in [429, 500, 502, 503, 504]:
                        # Convert to retryable error and continue with retry logic
                        last_exception = TikTokAdsAPIError(f"HTTP {status_code} error: {str(e)}", response=e.response)

                        if attempt == max_retries:
                            logger.exception(
                                "tiktok_ads_max_retries_exceeded",
                                function=func.__name__,
                                attempt=attempt + 1,
                                max_retries=max_retries,
                                error=str(last_exception),
                                http_status=status_code,
                            )
                            raise last_exception

                        delay = base_delay * (multiplier**attempt)

                        logger.warning(
                            "tiktok_ads_http_retry_attempt",
                            function=func.__name__,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            http_status=status_code,
                            error=str(e),
                        )

                        time.sleep(delay)
                        continue

                # Non-retryable HTTP error, re-raise immediately
                logger.exception(
                    "tiktok_ads_non_retryable_http_error",
                    function=func.__name__,
                    error=str(e),
                    http_status=getattr(e.response, "status_code", None) if hasattr(e, "response") else None,
                )
                raise
            except (Timeout, RequestException) as e:
                # Network errors are retryable
                last_exception = TikTokAdsAPIError(f"Network error: {str(e)}")

                if attempt == max_retries:
                    logger.exception(
                        "tiktok_ads_max_retries_exceeded",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(last_exception),
                        error_type="network",
                    )
                    raise last_exception

                delay = base_delay * (multiplier**attempt)

                logger.warning(
                    "tiktok_ads_network_retry_attempt",
                    function=func.__name__,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    error=str(e),
                )

                time.sleep(delay)
            except Exception as e:
                # Non-retryable exception, re-raise immediately
                logger.exception(
                    "tiktok_ads_non_retryable_error", function=func.__name__, error=str(e), error_type=type(e).__name__
                )
                raise

        # This should never be reached, but just in case
        if last_exception:
            raise last_exception

    return wrapper


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
        # If there isn't an incremental field last value, we fetch the last year of data
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
        chunk_end = current_start + timedelta(days=chunk_days - 1)

        if chunk_end > end_dt:
            chunk_end = end_dt

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
                error_message = json_data.get("message", "Unknown API error")
                logger.error(
                    "tiktok_ads_api_error",
                    api_code=api_code,
                    message=error_message,
                    response_status=response.status_code,
                )

                # Only retry specific error codes that are retryable (server/rate limit errors)
                retryable_codes = [
                    40100,  # QPS limit reached (confirmed from our tests - 20 QPS limit)
                    50000,  # Internal server error
                    50001,  # Service temporarily unavailable
                    50002,  # Service error
                ]

                if api_code in retryable_codes:
                    # Raise exception for retryable API errors
                    raise TikTokAdsAPIError(
                        f"TikTok API error: {error_message} (code: {api_code})", api_code=api_code, response=response
                    )
                else:
                    # Non-retryable error - raise a different exception
                    raise ValueError(f"TikTok API client error (non-retryable): {error_message} (code: {api_code})")
        except TikTokAdsAPIError:
            # Re-raise TikTok API errors
            raise
        except ValueError:
            # Re-raise ValueError (non-retryable errors) without wrapping
            raise
        except Exception as e:
            self._has_next_page = False
            logger.exception("tiktok_ads_paginator_error", error=str(e))
            # Raise exception for JSON parsing or other errors
            raise TikTokAdsAPIError(f"Failed to parse TikTok API response: {str(e)}", response=response)

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
