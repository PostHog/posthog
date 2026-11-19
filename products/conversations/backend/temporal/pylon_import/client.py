"""Pylon REST API client for historical issue import."""

from __future__ import annotations

import re
import time
import random
from dataclasses import field
from typing import Any

import requests
import structlog
from requests import Response

from posthog.dataclasses import frozen

from products.conversations.backend.temporal.pylon_import.constants import MAX_CONCURRENT_BATCH_WORKFLOWS
from products.conversations.backend.temporal.ticket_import.attachment_download import (
    AttachmentDownloadError,
    DownloadedAttachment,
    download_attachment,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)

REGION_HOSTS: dict[str, str] = {
    "us": "api.usepylon.com",
    "eu": "api.eu.usepylon.com",
}
EU_TOKEN_PREFIX = "pylon_api_eu_"

ISSUES_PER_PAGE = 200
MESSAGES_PER_PAGE = 1000
MAX_MESSAGE_PAGES = 50

# The search endpoint sorts by creation time, oldest first, so issues created during a long
# import land on the last pages instead of shifting the pages already read.
_ISSUE_SORT = [{"field": "created_at", "order": "asc"}]
# Matches every issue. The filter is optional in the API reference, but sending one keeps the
# request in the documented shape.
_ALL_ISSUES_FILTER = {"field": "created_at", "operator": "time_is_after", "value": "1970-01-01T00:00:00Z"}

# This runs inside a Temporal activity thread, so a long wait is handed to Temporal's RetryPolicy
# instead of pinning a thread-pool slot.
MAX_RATE_LIMIT_RETRIES = 6
MAX_RATE_LIMIT_SLEEP_SECONDS = 30
DEFAULT_RATE_LIMIT_SLEEP_SECONDS = 2
# Start pacing when an endpoint's allowance is nearly spent, so the import slows down before
# Pylon answers 429.
PACE_BELOW_REMAINING = 5
MAX_PACE_SLEEP_SECONDS = 5.0

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class PylonRateLimitError(Exception):
    """Raised when Pylon keeps rate-limiting beyond the in-thread retry budget.

    Retryable by default, so Temporal's RetryPolicy reschedules the activity.
    """


class PylonNotFoundError(Exception):
    """Raised when Pylon answers 404, so a caller can tell a deleted record from an outage."""


class PylonIncompleteIssueError(Exception):
    """Raised when an issue has more messages than the import will page through.

    Importing the collected prefix would mark the ticket done, and deduplication would then stop
    later runs from fetching the rest, so the issue fails instead.
    """


def is_retryable_error(exc: BaseException) -> bool:
    """True for failures a later attempt can fix: rate limits, timeouts, connection errors, 5xx."""
    if isinstance(exc, AttachmentDownloadError):
        return exc.retryable
    # ChunkedEncodingError and ContentDecodingError are a connection dropping mid-body; they
    # subclass RequestException, not ConnectionError.
    if isinstance(
        exc,
        PylonRateLimitError
        | requests.ConnectionError
        | requests.Timeout
        | requests.exceptions.ChunkedEncodingError
        | requests.exceptions.ContentDecodingError,
    ):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500
    return False


@frozen
class PylonCredentials:
    region: str
    api_token: str = field(repr=False)


def api_host_for_region(region: str) -> str:
    host = REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown Pylon region: {region!r}")
    return host


def _validate_id(kind: str, value: str) -> None:
    # Ids come from Pylon's own responses, but they're interpolated into the path, so keep them
    # to the characters of a UUID or an issue number.
    if not _ID_RE.match(value):
        raise ValueError(f"Invalid Pylon {kind} id: {value!r}")


def _header_int(response: Response, name: str) -> int | None:
    try:
        return int(response.headers.get(name, ""))
    except ValueError:
        return None


def _rate_limit_sleep_seconds(response: Response, attempt: int) -> float:
    # Retry-After is the wait until the next request can succeed. Other workers of the same
    # import draw on the same allowance, so back off and add jitter to keep them from colliding.
    retry_after = _header_int(response, "Retry-After")
    base = DEFAULT_RATE_LIMIT_SLEEP_SECONDS if retry_after is None else max(1, retry_after)
    return base + attempt + random.uniform(0, 1)


def _next_cursor(data: dict[str, Any], current: str | None) -> str | None:
    pagination = data.get("pagination") or {}
    cursor = pagination.get("cursor") if pagination.get("has_next_page") else None
    # A cursor that does not advance would repeat the same page forever.
    if not cursor or cursor == current:
        return None
    return str(cursor)


def _session(api_token: str) -> requests.Session:
    # The bearer token is a reusable workspace credential. Mask it in logged URLs and disable
    # sample capture so the Authorization header can't leak into HTTP telemetry. Redirects are
    # off so a credentialed request never follows one to another origin.
    return make_tracked_session(redact_values=(api_token,), capture=False, allow_redirects=False)


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


class PylonImportClient:
    def __init__(self, credentials: PylonCredentials) -> None:
        self._base_url = f"https://{api_host_for_region(credentials.region)}"
        self._session = _session(credentials.api_token)
        self._headers = _headers(credentials.api_token)
        self._status_categories: dict[str, str] | None = None

    def _handle_rate_limit(self, response: Response, path: str, attempt: int) -> None:
        sleep_seconds = _rate_limit_sleep_seconds(response, attempt)
        if attempt >= MAX_RATE_LIMIT_RETRIES or sleep_seconds > MAX_RATE_LIMIT_SLEEP_SECONDS:
            logger.warning("pylon_import_rate_limited_giving_up", sleep=sleep_seconds, path=path, attempt=attempt)
            raise PylonRateLimitError(
                f"Pylon rate limit exceeded in-thread retry budget (sleep={sleep_seconds:.0f}s, attempt={attempt})"
            )
        logger.warning("pylon_import_rate_limited", sleep=sleep_seconds, path=path, attempt=attempt)
        time.sleep(sleep_seconds)

    def _pace(self, response: Response) -> None:
        # An endpoint's allowance refills gradually over a minute. Near the end of it, wait one
        # refill interval per concurrent batch, which keeps the import at the refill rate.
        remaining = _header_int(response, "X-Rate-Limit-Remaining")
        limit = _header_int(response, "X-Rate-Limit-Limit")
        if remaining is None or not limit or limit <= 0 or remaining > PACE_BELOW_REMAINING:
            return
        time.sleep(min(60 / limit * MAX_CONCURRENT_BATCH_WORKFLOWS, MAX_PACE_SLEEP_SECONDS))

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Response:
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            response = self._session.request(method, url, headers=self._headers, params=params, json=json, timeout=60)
            if response.status_code != 429:
                self._pace(response)
                return response
            self._handle_rate_limit(response, path, attempt)
            attempt += 1

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._send(method, path, params=params, json=json)
        response.raise_for_status()
        return response.json()

    def list_issue_ids_page(self, *, cursor: str | None = None) -> tuple[list[str], str | None]:
        """Return one page of issue ids and the cursor for the next page (None at the end)."""
        body: dict[str, Any] = {"limit": ISSUES_PER_PAGE, "sort": _ISSUE_SORT, "filter": _ALL_ISSUES_FILTER}
        if cursor:
            body["cursor"] = cursor
        data = self._request("POST", "/issues/search", json=body)
        ids = [str(issue["id"]) for issue in data.get("data") or [] if issue.get("id")]
        return ids, _next_cursor(data, cursor)

    def fetch_issue(self, issue_id: str) -> dict[str, Any]:
        _validate_id("issue", issue_id)
        return self._request("GET", f"/issues/{issue_id}").get("data") or {}

    def fetch_messages(self, issue_id: str) -> list[dict[str, Any]]:
        """Fetch every message on an issue, replies and internal notes, oldest first."""
        _validate_id("issue", issue_id)
        path = f"/issues/{issue_id}/messages"
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_MESSAGE_PAGES):
            params: dict[str, Any] = {"limit": MESSAGES_PER_PAGE}
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", path, params=params)
            messages.extend(data.get("data") or [])
            cursor = _next_cursor(data, cursor)
            if cursor is None:
                return messages
        raise PylonIncompleteIssueError(f"Pylon issue {issue_id} has more than {MAX_MESSAGE_PAGES} pages of messages")

    def fetch_contact(self, contact_id: str) -> dict[str, Any]:
        _validate_id("contact", contact_id)
        response = self._send("GET", f"/contacts/{contact_id}")
        if response.status_code == 404:
            raise PylonNotFoundError(f"Pylon contact {contact_id} not found")
        response.raise_for_status()
        return response.json().get("data") or {}

    def issue_status_categories(self) -> dict[str, str]:
        """Map each issue status slug to its category. Fetched once per client, on first use."""
        if self._status_categories is None:
            statuses = self._request("GET", "/issue-statuses").get("data") or []
            self._status_categories = {
                str(status["slug"]).lower(): str(status.get("category") or "")
                for status in statuses
                if status.get("slug")
            }
        return self._status_categories

    def download_attachment(self, url: str, *, max_bytes: int) -> DownloadedAttachment:
        """Download a message file. Pylon file URLs are signed links, so the token is not sent."""
        return download_attachment(url, max_bytes=max_bytes)


def _candidate_regions(api_token: str) -> list[str]:
    # A token created before Pylon added region prefixes has none, so the prefix only sets the
    # order. The other region is still tried.
    return ["eu", "us"] if api_token.startswith(EU_TOKEN_PREFIX) else ["us", "eu"]


def resolve_pylon_credentials(api_token: str) -> PylonCredentials | None:
    """Find the region that accepts the token, and confirm the token can read issues.

    /me would succeed for a token whose role cannot read issues, and the import would then fail
    later in the background, so this probes the issue search instead. Runs synchronously inside
    the settings-page create() request handler, so it has a short timeout and treats any failure
    to reach and authenticate as invalid credentials.
    """
    session = _session(api_token)
    for region in _candidate_regions(api_token):
        try:
            response = session.post(
                f"https://{api_host_for_region(region)}/issues/search",
                json={"limit": 1, "filter": _ALL_ISSUES_FILTER},
                headers=_headers(api_token),
                timeout=10,
            )
        except Exception:
            return None
        if response.status_code == 200:
            return PylonCredentials(region=region, api_token=api_token)
        # Pylon answers 401 when a token belongs to the other region.
        if response.status_code != 401:
            return None
    return None
