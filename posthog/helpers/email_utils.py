"""
Provides utilities for handling email addresses with case-insensitive behavior
while maintaining backwards compatibility with existing data that may have mixed casing.
"""

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import MultipleObjectsReturned
from django.db.models import QuerySet

import requests
import structlog
import posthoganalytics

from posthog.settings.web import TWO_FACTOR_REMEMBER_COOKIE_AGE

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


class EmailNormalizer:
    @staticmethod
    def normalize(email: str) -> str:
        if not email:
            return email

        return email.lower()


class EmailLookupHandler:
    @staticmethod
    def get_user_by_email(email: str, is_active: Optional[bool] = True) -> Optional["User"]:
        """
        Get user by email with backwards compatibility.
        First tries exact match (for existing users), then case-insensitive fallback.

        Handles the edge case where multiple users exist with case variations of the same email
        (e.g., test@email.com, Test@email.com, TEST@email.com) by:
        1. Preferring exact case match if it exists
        2. Returning the first case-insensitive match deterministically if no exact match
        """
        from posthog.models.user import User

        queryset = User.objects.filter(is_active=is_active) if is_active else User.objects.all()

        # First try: exact match (preserves existing behavior)
        try:
            return queryset.get(email=email)
        except User.DoesNotExist:
            pass

        # Second try: case-insensitive match
        try:
            return queryset.get(email__iexact=email)
        except User.DoesNotExist:
            return None
        except MultipleObjectsReturned:
            # Handle multiple case variations of the same email
            return EmailMultiRecordHandler.handle_multiple_users(
                queryset.filter(email__iexact=email), email, "user_lookup"
            )


class EmailMultiRecordHandler:
    """
    Utility class for handling cases where multiple records exist with case variations of the same email.
    Provides deterministic behavior and comprehensive logging for monitoring and cleanup.
    """

    @staticmethod
    def handle_multiple_users(queryset: QuerySet, email: str, context: str) -> Optional["User"]:
        """
        Handle multiple user records with case variations of the same email.

        Returns:
            Last logged in user deterministically
        """
        case_insensitive_matches = queryset.order_by("-last_login")
        user_count = case_insensitive_matches.count()
        last_logged_in_user = case_insensitive_matches.first()

        if user_count > 1:
            email_variations = list(case_insensitive_matches.values_list("email", flat=True))
            last_logged_in_user_id = last_logged_in_user.id if last_logged_in_user else None

            posthoganalytics.capture(
                "multiple users with email case variations",
                properties={
                    "email": email,
                    "user_count": user_count,
                    "email_variations": email_variations,
                    "last_logged_in_user_id": last_logged_in_user_id,
                },
            )

            logger.warning(
                f"Multiple users with case variations of email '{email}' during {context}. "
                f"Found {user_count} variations: {email_variations}. "
                f"Returning last logged in user (ID: {last_logged_in_user_id})"
            )

        return last_logged_in_user


class EmailValidationHelper:
    @staticmethod
    def user_exists(email: str) -> bool:
        return EmailLookupHandler.get_user_by_email(email) is not None


ESP_SUPPRESSION_CACHE_TTL = TWO_FACTOR_REMEMBER_COOKIE_AGE  # 30 days, aligned with remember-me cookie
ESP_SUPPRESSION_ERROR_CACHE_TTL = 60  # Short TTL for errors to prevent thundering herd during outages
ESP_SUPPRESSION_API_TIMEOUT = 5


@dataclass
class ESPSuppressionResult:
    is_suppressed: bool
    from_cache: bool
    reason: Optional[str] = None


def _esp_suppression_api_failure_fallback(
    email: str,
    error_type: str,
    error_details: Optional[str] = None,
    api_status_code: Optional[int] = None,
) -> ESPSuppressionResult:
    """
    When the ESP suppression API fails, we allow users through (treat as suppressed)
    to avoid blocking logins when Customer.io is unavailable.

    We cache the error state briefly to prevent thundering herd during outages.
    """
    cache.set(_get_esp_suppression_error_cache_key(email), True, ESP_SUPPRESSION_ERROR_CACHE_TTL)

    logger.warning(
        "ESP suppression API failure - allowing user through",
        error_type=error_type,
        error_details=error_details,
        cached_for_seconds=ESP_SUPPRESSION_ERROR_CACHE_TTL,
    )
    _capture_esp_suppression_analytics(
        email=email,
        outcome="api_failure_fallback",
        from_cache=False,
        api_called=True,
        api_status_code=api_status_code,
        error_type=error_type,
    )
    return ESPSuppressionResult(is_suppressed=True, from_cache=False, reason="api_failure_fallback")


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _get_esp_suppression_cache_key(email: str) -> str:
    return f"email_mfa_suppressed:{_hash_email(email)}"


def _get_esp_suppression_error_cache_key(email: str) -> str:
    return f"email_mfa_suppressed_error:{_hash_email(email)}"


def _capture_esp_suppression_analytics(
    email: str,
    outcome: str,
    from_cache: bool,
    cache_type: Optional[str] = None,
    api_called: bool = False,
    api_status_code: Optional[int] = None,
    error_type: Optional[str] = None,
) -> None:
    try:
        posthoganalytics.capture(
            distinct_id=_hash_email(email),
            event="esp_suppression_check",
            properties={
                "outcome": outcome,
                "from_cache": from_cache,
                "cache_type": cache_type,
                "api_called": api_called,
                "api_status_code": api_status_code,
                "error_type": error_type,
            },
        )
    except Exception as e:
        logger.warning("Failed to capture ESP suppression analytics", error=str(e))


def check_esp_suppression(email: str) -> ESPSuppressionResult:
    """Check if an email address is on the ESP suppression list."""
    if not email:
        return ESPSuppressionResult(is_suppressed=False, from_cache=False, reason="empty_email")

    cache_key = _get_esp_suppression_cache_key(email)
    cached_result = cache.get(cache_key)

    if cached_result is not None:
        _capture_esp_suppression_analytics(
            email=email,
            outcome="suppressed" if cached_result else "not_suppressed",
            from_cache=True,
            cache_type="success_cache",
        )
        return ESPSuppressionResult(
            is_suppressed=cached_result, from_cache=True, reason="suppressed" if cached_result else None
        )

    # Check if we recently had an API error for this email (prevents thundering herd)
    if cache.get(_get_esp_suppression_error_cache_key(email)):
        logger.info(
            "ESP suppression check returning cached error fallback",
            email_hash=_hash_email(email)[:8],
        )
        _capture_esp_suppression_analytics(
            email=email,
            outcome="api_failure_fallback",
            from_cache=True,
            cache_type="error_cache",
        )
        return ESPSuppressionResult(is_suppressed=True, from_cache=True, reason="api_failure_fallback")

    try:
        api_response = _fetch_esp_suppression_from_api(email)
        cache.set(cache_key, api_response.is_suppressed, ESP_SUPPRESSION_CACHE_TTL)
        _capture_esp_suppression_analytics(
            email=email,
            outcome="suppressed" if api_response.is_suppressed else "not_suppressed",
            from_cache=False,
            api_called=True,
            api_status_code=api_response.status_code,
        )
        return ESPSuppressionResult(
            is_suppressed=api_response.is_suppressed,
            from_cache=False,
            reason="suppressed" if api_response.is_suppressed else None,
        )
    except ESPSuppressionAPIError as e:
        if e.error_type == "no_api_key":
            return ESPSuppressionResult(is_suppressed=False, from_cache=False, reason="no_api_key")
        return _esp_suppression_api_failure_fallback(email, e.error_type, e.error_details, e.status_code)
    except Exception as e:
        logger.exception("ESP suppression check unexpected error", error=str(e))
        return _esp_suppression_api_failure_fallback(email, "unexpected_error", str(e))


def _parse_esp_suppression_response(data: Any) -> bool:
    if not data:
        return False
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return bool(data.get("suppressed", False)) or bool(data.get("suppressions", []))
    return False


@dataclass
class ESPSuppressionAPIResponse:
    is_suppressed: bool
    status_code: int


class ESPSuppressionAPIError(Exception):
    def __init__(self, error_type: str, error_details: Optional[str] = None, status_code: Optional[int] = None):
        self.error_type = error_type
        self.error_details = error_details
        self.status_code = status_code
        super().__init__(f"{error_type}: {error_details}")


def _fetch_esp_suppression_from_api(email: str) -> ESPSuppressionAPIResponse:
    """Fetches suppression status from Customer.io API."""
    if not settings.CUSTOMER_IO_API_KEY:
        raise ESPSuppressionAPIError("no_api_key")

    headers = {
        "Authorization": f"Bearer {settings.CUSTOMER_IO_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{settings.CUSTOMER_IO_API_URL}/v1/esp/suppressions",
            params={"email": email},
            headers=headers,
            timeout=ESP_SUPPRESSION_API_TIMEOUT,
        )

        if response.status_code == 200:
            data = response.json()
            return ESPSuppressionAPIResponse(
                is_suppressed=_parse_esp_suppression_response(data),
                status_code=200,
            )
        elif response.status_code == 404:
            return ESPSuppressionAPIResponse(is_suppressed=False, status_code=404)
        else:
            raise ESPSuppressionAPIError(
                "http_error",
                f"status={response.status_code} body={response.text[:200] if response.text else ''}",
                status_code=response.status_code,
            )

    except requests.Timeout:
        raise ESPSuppressionAPIError("timeout")
    except requests.RequestException as e:
        raise ESPSuppressionAPIError("network_error", str(e))
