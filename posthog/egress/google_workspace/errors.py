from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime

from django.utils import timezone

import requests


class GoogleWorkspaceTransientError(Exception):
    """A Google Workspace API returned a transient status (HTTP 429 or 5xx).

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


def raise_if_transient_google_workspace_status(response: requests.Response, operation: str) -> None:
    """Raise ``GoogleWorkspaceTransientError`` when the status is transient (HTTP 429 or 5xx).

    The message carries only the status code, never the response body, so one failure mode maps to
    one error tracking issue instead of fingerprinting on the body text.
    """
    status_code = response.status_code
    if status_code == 429 or status_code >= 500:
        raise GoogleWorkspaceTransientError(
            f"{operation} returned {status_code}",
            retry_after=_parse_retry_after(response),
        )
