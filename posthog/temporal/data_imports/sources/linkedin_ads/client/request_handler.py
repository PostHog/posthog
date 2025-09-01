"""LinkedIn Ads API request handling with retry and rate limiting logic."""

import time
import random
from typing import Optional

import requests
import structlog

from posthog.exceptions_capture import capture_exception

from ..utils.constants import API_MAX_RETRIES, API_RATE_LIMIT_DELAY, API_RETRY_DELAY, API_TIMEOUT
from ..utils.types import RequestParams, ResponseData
from .exceptions import LinkedinAdsError, LinkedinAdsErrorHandler

logger = structlog.get_logger(__name__)


class LinkedinAdsRequestHandler:
    """Handles HTTP requests to LinkedIn Ads API with retry logic and error handling."""

    def __init__(self, session: requests.Session):
        """Initialize request handler.

        Args:
            session: Configured requests session with authentication headers
        """
        self.session = session
        self.max_retries = API_MAX_RETRIES
        self.retry_delay = API_RETRY_DELAY
        self.rate_limit_delay = API_RATE_LIMIT_DELAY
        self.timeout = API_TIMEOUT
        self.error_handler = LinkedinAdsErrorHandler()

    def make_request(self, url: str, params: Optional[RequestParams] = None) -> ResponseData:
        """Make a request to LinkedIn API with comprehensive retry logic.

        Args:
            url: Full URL to make request to
            params: Query parameters for the request

        Returns:
            JSON response from the API

        Raises:
            LinkedinAdsError: For various API errors
            requests.exceptions.RequestException: For request failures
        """
        endpoint = url.split("/")[-1]  # Extract endpoint for logging

        for attempt in range(self.max_retries + 1):
            try:
                response = self._execute_request(url, params)

                # Handle error responses
                if response.status_code >= 400:
                    if response.status_code == 429 and attempt < self.max_retries:
                        self._handle_rate_limit(response, endpoint, attempt)
                        continue
                    elif response.status_code >= 500 and attempt < self.max_retries:
                        self._handle_server_error(response, endpoint, attempt)
                        continue
                    else:
                        self.error_handler.handle_response_error(response, endpoint)

                # Success - parse and return JSON
                return self.error_handler.parse_json_response(response, endpoint)

            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    self._handle_timeout(endpoint, attempt)
                    continue
                else:
                    self._raise_timeout_error(endpoint)

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    self._handle_request_exception(e, endpoint, attempt)
                    continue
                else:
                    self._raise_request_exception(e, endpoint)

        # This should never be reached
        raise LinkedinAdsError("Max retries exceeded")

    def _execute_request(self, url: str, params: Optional[RequestParams] = None) -> requests.Response:
        """Execute the actual HTTP request.

        Args:
            url: URL to request
            params: Query parameters

        Returns:
            HTTP response object
        """
        if params:
            # Build query string manually to avoid encoding issues
            query_parts = [f"{key}={value}" for key, value in params.items()]
            query_string = "&".join(query_parts)
            url = f"{url}?{query_string}"

        return self.session.get(url, timeout=self.timeout)

    def _handle_rate_limit(self, response: requests.Response, endpoint: str, attempt: int) -> None:
        """Handle rate limit responses with appropriate delays.

        Args:
            response: HTTP response object
            endpoint: API endpoint being called
            attempt: Current attempt number
        """
        retry_after_header = response.headers.get("Retry-After", str(self.rate_limit_delay))

        try:
            retry_after = int(retry_after_header)
        except ValueError:
            # If Retry-After is not an integer, use default delay
            retry_after = self.rate_limit_delay

        logger.warning(
            "LinkedIn API rate limit hit, retrying", endpoint=endpoint, attempt=attempt + 1, retry_after=retry_after
        )
        time.sleep(retry_after)

    def _handle_server_error(self, response: requests.Response, endpoint: str, attempt: int) -> None:
        """Handle server error responses with exponential backoff.

        Args:
            response: HTTP response object
            endpoint: API endpoint being called
            attempt: Current attempt number
        """
        delay = self.retry_delay * (2**attempt) + random.uniform(0, 1)
        logger.warning(
            "LinkedIn API server error, retrying",
            endpoint=endpoint,
            attempt=attempt + 1,
            status_code=response.status_code,
            delay=delay,
        )
        time.sleep(delay)

    def _handle_timeout(self, endpoint: str, attempt: int) -> None:
        """Handle timeout exceptions with exponential backoff.

        Args:
            endpoint: API endpoint being called
            attempt: Current attempt number
        """
        delay = self.retry_delay * (2**attempt)
        logger.warning("LinkedIn API request timeout, retrying", endpoint=endpoint, attempt=attempt + 1, delay=delay)
        time.sleep(delay)

    def _handle_request_exception(
        self, error: requests.exceptions.RequestException, endpoint: str, attempt: int
    ) -> None:
        """Handle general request exceptions with exponential backoff.

        Args:
            error: Request exception that occurred
            endpoint: API endpoint being called
            attempt: Current attempt number
        """
        delay = self.retry_delay * (2**attempt)
        logger.warning(
            "LinkedIn API request failed, retrying",
            endpoint=endpoint,
            attempt=attempt + 1,
            error=str(error),
            delay=delay,
        )
        time.sleep(delay)

    def _raise_timeout_error(self, endpoint: str) -> None:
        """Raise timeout error after max retries exceeded.

        Args:
            endpoint: API endpoint being called
        """
        error_msg = "LinkedIn API request timeout"
        logger.exception("LinkedIn API request timeout", endpoint=endpoint)
        capture_exception(LinkedinAdsError(error_msg))
        raise LinkedinAdsError(error_msg)

    def _raise_request_exception(self, error: requests.exceptions.RequestException, endpoint: str) -> None:
        """Raise request exception after max retries exceeded.

        Args:
            error: Request exception that occurred
            endpoint: API endpoint being called
        """
        logger.exception("LinkedIn API request failed", error=str(error), endpoint=endpoint)
        capture_exception(error)
        raise
