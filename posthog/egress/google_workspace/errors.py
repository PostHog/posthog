from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime

from django.utils import timezone

import requests


class GoogleWorkspaceTransientError(Exception):
    """A Google Workspace API returned a transient status.

    The sync recovers by retrying, so the Temporal activity should retry quietly rather than open
    an error tracking issue. ``retry_after`` carries the wait Google asked for, when it sent a
    ``Retry-After`` header.
    """

    def __init__(self, message: str, *, retry_after: timedelta | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(response: requests.Response) -> timedelta | None:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return timedelta(seconds=int(raw))
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = retry_at - timezone.now()
    return delay if delay > timedelta(0) else timedelta(0)


# Google answers HTTP 403 both for throttling and for permission failures, so the reason code in the
# body is the only way to separate them. Only these two documented usageLimits reasons clear on a
# backoff. A daily or project quota reason does not clear that way, and a permission reason such as
# insufficientPermissions must stay reportable so a revoked scope still opens an issue.
_TRANSIENT_FORBIDDEN_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


def _has_transient_forbidden_reason(response: requests.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    errors = error.get("errors")
    if not isinstance(errors, list):
        return False
    return any(isinstance(item, dict) and item.get("reason") in _TRANSIENT_FORBIDDEN_REASONS for item in errors)


def _is_transient(response: requests.Response) -> bool:
    status_code = response.status_code
    if status_code == 429 or status_code >= 500:
        return True
    return status_code == 403 and _has_transient_forbidden_reason(response)


def raise_if_transient_google_workspace_status(response: requests.Response, operation: str) -> None:
    """Raise ``GoogleWorkspaceTransientError`` when the status is transient.

    Transient means HTTP 429, any 5xx, or a 403 that carries a documented throttling reason.
    The message carries only the status code, never the response body, so one failure mode maps to
    one error tracking issue instead of fingerprinting on the body text.
    """
    if _is_transient(response):
        raise GoogleWorkspaceTransientError(
            f"{operation} returned {response.status_code}",
            retry_after=_parse_retry_after(response),
        )
