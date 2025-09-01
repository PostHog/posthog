"""LinkedIn Ads API exceptions and error handling."""

from typing import Any

import structlog

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class LinkedinAdsError(Exception):
    """Base exception for LinkedIn Ads API errors."""

    pass


class LinkedinAdsAuthError(LinkedinAdsError):
    """Authentication error for LinkedIn Ads API."""

    pass


class LinkedinAdsRateLimitError(LinkedinAdsError):
    """Rate limit error for LinkedIn Ads API."""

    pass


class LinkedinAdsErrorHandler:
    """Centralized error handling for LinkedIn Ads API responses."""

    @staticmethod
    def handle_response_error(response, endpoint: str) -> None:
        """Handle HTTP error responses from LinkedIn API.

        Args:
            response: HTTP response object
            endpoint: API endpoint that was called

        Raises:
            LinkedinAdsAuthError: For 401 authentication errors
            LinkedinAdsRateLimitError: For 429 rate limit errors
            LinkedinAdsError: For other client/server errors
        """
        status_code = response.status_code

        if status_code == 401:
            error_msg = "LinkedIn API authentication failed. Please check your access token."
            try:
                error_detail = response.json().get("message", "")
                if error_detail:
                    error_msg += f" Details: {error_detail}"
            except ValueError:
                pass

            logger.error("LinkedIn API auth error", endpoint=endpoint, status_code=status_code)
            capture_exception(LinkedinAdsAuthError(error_msg))
            raise LinkedinAdsAuthError(error_msg)

        elif status_code == 429:
            try:
                retry_after = int(response.headers.get("Retry-After", "60"))
            except ValueError:
                retry_after = 60

            error_msg = f"LinkedIn API rate limit exceeded. Retry after {retry_after} seconds."
            logger.error("LinkedIn API rate limit exceeded", endpoint=endpoint)
            capture_exception(LinkedinAdsRateLimitError(error_msg))
            raise LinkedinAdsRateLimitError(error_msg)

        elif status_code >= 500:
            error_msg = f"LinkedIn API server error: {status_code}"
            logger.error(
                "LinkedIn API server error",
                endpoint=endpoint,
                status_code=status_code,
                response_text=response.text[:500],
            )
            capture_exception(LinkedinAdsError(error_msg))
            raise LinkedinAdsError(error_msg)

        elif status_code >= 400:
            error_msg = f"LinkedIn API client error: {status_code}"
            try:
                error_detail = response.json().get("message", response.text[:200])
                if error_detail:
                    error_msg += f" Details: {error_detail}"
            except ValueError:
                error_msg += f" Response: {response.text[:200]}"

            logger.error(
                "LinkedIn API client error",
                endpoint=endpoint,
                status_code=status_code,
                response_text=response.text[:500],
            )
            capture_exception(LinkedinAdsError(error_msg))
            raise LinkedinAdsError(error_msg)

    @staticmethod
    def parse_json_response(response, endpoint: str) -> dict[str, Any]:
        """Parse JSON response with error handling.

        Args:
            response: HTTP response object
            endpoint: API endpoint that was called

        Returns:
            Parsed JSON data

        Raises:
            LinkedinAdsError: If JSON parsing fails
        """
        try:
            return response.json()
        except ValueError as e:
            logger.exception(
                "Failed to parse JSON response",
                endpoint=endpoint,
                status_code=response.status_code,
                response_text=response.text[:200],
            )
            raise LinkedinAdsError(f"Invalid JSON response from LinkedIn API: {str(e)}")
