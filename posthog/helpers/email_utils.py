"""
Email-related helpers: address normalization, ESP suppression lookups, user
lookup by email, and display-name / message validation.
"""

import re
import html
import hashlib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Optional, cast, overload
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import MultipleObjectsReturned
from django.db.models import QuerySet

import requests
import structlog
import posthoganalytics
from rest_framework import serializers

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


_URL_SCHEME_RE = re.compile(
    r"[a-z][a-z0-9+.\-]*://"
    r"|\b(?:javascript|data|vbscript|file|ftp|mailto|tel|sms):"
    r"|www\.",
    re.IGNORECASE,
)
_BARE_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b",
    re.IGNORECASE,
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f\u0085\u2028\u2029]")
_NON_NEWLINE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u0085\u2028\u2029]")
_BRACKET_RE = re.compile(r"[<>]")
_INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

_URL_ERROR = "URLs are not allowed in this field."
_CONTROL_ERROR = "Line breaks and control characters are not allowed in this field."
_BRACKET_ERROR = "Angle brackets are not allowed in this field."
_INVISIBLE_ERROR = "Invisible or direction-override characters are not allowed in this field."


def _check_shared(value: str) -> None:
    """
    Run the checks shared between display names and message bodies against an
    NFKC-normalized copy of `value`. Normalization folds fullwidth / compat
    variants (e.g. `ｈｔｔｐ：／／` \u2192 `http://`) before regex matching.
    """
    normalized = unicodedata.normalize("NFKC", value)
    if _INVISIBLE_CHAR_RE.search(normalized):
        raise serializers.ValidationError(_INVISIBLE_ERROR, code="invalid_invisible_char")
    if _BRACKET_RE.search(normalized):
        raise serializers.ValidationError(_BRACKET_ERROR, code="invalid_bracket")
    if _URL_SCHEME_RE.search(normalized):
        raise serializers.ValidationError(_URL_ERROR, code="invalid_url")


@overload
def validate_display_name(value: str) -> str: ...


@overload
def validate_display_name(value: None) -> None: ...


def validate_display_name(value: str | None) -> str | None:
    """
    Validate identity fields (`first_name`, `last_name`, organization name,
    invite recipient name). Rejects URL schemes (`https://`, `javascript:`,
    `www.`), line breaks, control characters, angle brackets, and zero-width /
    bidi characters. Bare domains (`google.com`) are allowed — users
    legitimately set those as org names, and `sanitize_email_string` defangs
    them at email render time. Returns the stripped value; empty / blank input
    passes through.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return stripped
    if _CONTROL_CHAR_RE.search(stripped):
        raise serializers.ValidationError(_CONTROL_ERROR, code="invalid_control_char")
    _check_shared(stripped)
    return stripped


def validate_message_body(value: str | None) -> str | None:
    """
    Validate a free-text message body. Newlines and tabs are allowed; URL
    schemes (`http://`, `javascript:`, `www.`, ...), non-newline control
    chars, angle brackets, and invisible chars are not. Bare domains are
    permitted so messages like "see the foo.py file" stay usable.
    """
    if value is None:
        return None
    if _NON_NEWLINE_CONTROL_RE.search(value):
        raise serializers.ValidationError(_CONTROL_ERROR, code="invalid_control_char")
    _check_shared(value)
    return value


def contains_bare_domain(value: str | None) -> bool:
    """
    True if `value` contains a bare domain (e.g. `example.com`) after NFKC
    normalization. The `validate_*` helpers above intentionally *allow* bare
    domains; callers that want to reject domains entirely (e.g. so mail clients
    can't auto-link them in a branded email) layer this check on top.
    """
    if not value:
        return False
    return bool(_BARE_DOMAIN_RE.search(unicodedata.normalize("NFKC", value)))


def _extract_error_code(err: serializers.ValidationError) -> str:
    """
    Pull the first `code` off a DRF ValidationError. `err.detail` is a union
    of ErrorDetail | list | dict (when raised from a serializer); for the
    single-field validators in this module we always raise the list form, but
    narrow defensively so mypy is happy and we don't crash if a caller hands
    us something unexpected.
    """
    detail = err.detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        return getattr(first, "code", "invalid") or "invalid"
    if isinstance(detail, dict) and detail:
        first = next(iter(detail.values()))
        if isinstance(first, list) and first:
            first = first[0]
        return getattr(first, "code", "invalid") or "invalid"
    return getattr(detail, "code", "invalid") or "invalid"


def _sanitize(
    value: str | None,
    *,
    validator: Callable[[str | None], str | None],
    log_event: str,
    fallback: str,
    context: Optional[dict] = None,
) -> str:
    """
    Core sanitize-with-fallback flow shared by `sanitize_display_name` and
    `sanitize_message_body`. Runs `validator`; on a ValidationError or a
    falsy result (None / empty / whitespace-only, depending on the validator),
    returns `fallback` and logs the rejection with `context` for diagnostics.
    """
    try:
        validated = validator(value)
    except serializers.ValidationError as err:
        logger.info(
            log_event,
            error_code=_extract_error_code(err),
            fallback=fallback,
            **(context or {}),
        )
        return fallback
    return validated or fallback


# `validate_display_name` is `@overload`-decorated to express the None-in / None-out
# relationship at call sites; mypy then can't match the overloaded type against the plain
# `Callable[[str | None], str | None]` signature `_sanitize` expects. Cast once here —
# `_sanitize` always passes through the `str | None` overload at runtime.
_Validator = Callable[[Optional[str]], Optional[str]]

# Display-name fallback for identity fields (organization name, inviter / invitee first name).
# Use in email-sending tasks where dropping the email entirely on a bad legacy value (e.g. an
# organisation name that happens to be a URL) would be more harmful than substituting a
# generic placeholder.
sanitize_display_name = partial(
    _sanitize,
    validator=cast(_Validator, validate_display_name),
    log_event="email_utils.display_name_sanitized",
)

# Message-body fallback. Defaults `fallback` to an empty string so the optional message block
# in templates collapses cleanly when an inviter's free-text message fails validation.
sanitize_message_body = partial(
    _sanitize,
    validator=cast(_Validator, validate_message_body),
    log_event="email_utils.message_body_sanitized",
    fallback="",
)


# Zero-width space inserted after `.` and `:` to break auto-link patterns.
# We previously used `&#46;` / `&#58;` HTML entities, but Customer.io's
# template engine (TinyMCE-backed) decodes them on output, defeating the
# defang. ZWSP is a real Unicode codepoint, so it survives JSON transit and
# the ESP's template rendering. It's invisible to the recipient, but breaks
# the `\w+\.\w+` and `[a-z]+://` patterns mail-client auto-linkers scan for.
_ZWSP = "​"


def _defang_match(match: "re.Match[str]") -> str:
    return match.group(0).replace(".", f".{_ZWSP}").replace(":", f":{_ZWSP}")


def sanitize_email_string(value: str) -> str:
    """
    Sanitize a string for inclusion in email content (Customer.io
    `message_data` properties or Django email templates). Steps:

    1. NFKC-normalize so fullwidth / compatibility forms can't bypass the
       URL regexes (e.g. `ｈｔｔｐ：／／` → `http://`).
    2. Strip zero-width / direction-override / line-separator characters that
       could hide URL structure (`evil​.com` → `evil.com`). This runs *before*
       step 4 reintroduces zero-width spaces, so attacker-supplied invisibles
       can't survive but our defang ones can.
    3. HTML-escape so any embedded markup renders as text in the final email.
    4. Defang URL-shaped substrings: insert a zero-width space after each `.`
       and `:` inside a URL scheme (`https://`, `javascript:`, `www.`, ...) or
       a bare domain (`evil.com`) so mail clients do not auto-link them.

    Step 4 breaks the contiguous `\\w+\\.\\w+` / `[a-z]+://` patterns that
    mail-client auto-linkers scan for. The recipient still reads `evil.com`
    (the ZWSP is invisible) but the link is no longer clickable.
    """
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = _INVISIBLE_CHAR_RE.sub("", normalized)
    escaped = html.escape(cleaned)
    # No `.` or `:` means neither regex can match — skip the two passes.
    if "." not in escaped and ":" not in escaped:
        return escaped
    defanged = _URL_SCHEME_RE.sub(_defang_match, escaped)
    return _BARE_DOMAIN_RE.sub(_defang_match, defanged)


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


ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS = 86400  # 1 day
ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS = (
    60  # Short TTL for errors/rate-limits to prevent thundering herd during outages
)
ESP_SUPPRESSION_API_TIMEOUT_IN_SECONDS = 5


class ESPSuppressionReason(str, Enum):
    SUPPRESSED = "suppressed"
    EMPTY_EMAIL = "empty_email"
    NO_EMAIL_HTTP_SERVICE = "no_email_http_service"
    API_FAILURE_FALLBACK = "api_failure_fallback"


@dataclass
class ESPSuppressionResult:
    is_suppressed: bool
    from_cache: bool
    reason: Optional[ESPSuppressionReason] = None


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
    cache.set(
        _get_esp_suppression_error_cache_key(email),
        True,
        ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS,
    )

    logger.warning(
        "ESP suppression API failure - allowing user through",
        error_type=error_type,
        error_details=error_details,
        cached_for_seconds=ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS,
    )
    _capture_esp_suppression_analytics(
        email=email,
        outcome="api_failure_fallback",
        from_cache=False,
        api_called=True,
        api_status_code=api_status_code,
        error_type=error_type,
    )
    return ESPSuppressionResult(
        is_suppressed=True,
        from_cache=False,
        reason=ESPSuppressionReason.API_FAILURE_FALLBACK,
    )


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _get_esp_suppression_cache_key(email: str) -> str:
    return f"code_based_verification_suppressed:{_hash_email(email)}"


def _get_esp_suppression_error_cache_key(email: str) -> str:
    return f"code_based_verification_suppressed_error:{_hash_email(email)}"


def _capture_esp_suppression_analytics(
    email: str,
    outcome: str,
    from_cache: bool,
    cache_type: Optional[str] = None,
    api_called: bool = False,
    api_status_code: Optional[int] = None,
    error_type: Optional[str] = None,
    suppressions: Optional[list[dict]] = None,
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
                "suppressions": suppressions,
            },
        )
    except Exception as e:
        logger.warning("Failed to capture ESP suppression analytics", error=str(e))


def check_esp_suppression(email: str) -> ESPSuppressionResult:
    """Check if an email address is on the ESP suppression list."""
    if not email:
        return ESPSuppressionResult(
            is_suppressed=False,
            from_cache=False,
            reason=ESPSuppressionReason.EMPTY_EMAIL,
        )

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
            is_suppressed=cached_result,
            from_cache=True,
            reason=ESPSuppressionReason.SUPPRESSED if cached_result else None,
        )

    # Check if we recently had an API error for this email (prevents thundering herd)
    if cache.get(_get_esp_suppression_error_cache_key(email)):
        logger.info(
            "ESP suppression check returning cached error fallback",
            email_hash=_hash_email(email),
        )
        _capture_esp_suppression_analytics(
            email=email,
            outcome="api_failure_fallback",
            from_cache=True,
            cache_type="error_cache",
        )
        return ESPSuppressionResult(
            is_suppressed=True,
            from_cache=True,
            reason=ESPSuppressionReason.API_FAILURE_FALLBACK,
        )

    try:
        api_response = _fetch_esp_suppression_from_api(email)
        cache_ttl = api_response.cache_ttl
        cache.set(cache_key, api_response.is_suppressed, cache_ttl)
        _capture_esp_suppression_analytics(
            email=email,
            outcome="suppressed" if api_response.is_suppressed else "not_suppressed",
            from_cache=False,
            api_called=True,
            api_status_code=api_response.status_code,
            suppressions=api_response.suppressions,
        )
        return ESPSuppressionResult(
            is_suppressed=api_response.is_suppressed,
            from_cache=False,
            reason=ESPSuppressionReason.SUPPRESSED if api_response.is_suppressed else None,
        )
    except ESPSuppressionAPIError as e:
        return _esp_suppression_api_failure_fallback(email, e.error_type, e.error_details, e.status_code)
    except Exception as e:
        logger.exception("ESP suppression check unexpected error", error=str(e))
        return _esp_suppression_api_failure_fallback(email, "unexpected_error", str(e))


@dataclass
class ESPSuppressionAPIResponse:
    is_suppressed: bool
    status_code: int
    suppressions: Optional[list[dict]] = None
    cache_ttl: Optional[int] = ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS


class ESPSuppressionAPIError(Exception):
    def __init__(
        self,
        error_type: str,
        error_details: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        self.error_type = error_type
        self.error_details = error_details
        self.status_code = status_code
        super().__init__(f"{error_type}: {error_details}")


def _fetch_esp_suppression_from_api(email: str) -> ESPSuppressionAPIResponse:
    """Fetches suppression status from Customer.io API."""
    headers = {
        "Authorization": f"Bearer {settings.CUSTOMER_IO_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{settings.CUSTOMER_IO_API_URL}/v1/esp/search_suppression/{quote(email, safe='')}",
            headers=headers,
            timeout=ESP_SUPPRESSION_API_TIMEOUT_IN_SECONDS,
        )

        if response.status_code == 200:
            data = response.json()
            suppressions = data.get("suppressions") if data else None
            is_suppressed = bool(suppressions)
            return ESPSuppressionAPIResponse(
                is_suppressed=is_suppressed,
                status_code=200,
                suppressions=suppressions if is_suppressed else None,
            )
        elif response.status_code == 429:
            # Rate limited, determine as not suppressed but cache for short TTL
            return ESPSuppressionAPIResponse(
                is_suppressed=False,
                status_code=429,
                cache_ttl=ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS,
            )
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
