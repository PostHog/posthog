"""Zendesk Support API client for historical ticket import."""

from __future__ import annotations

import re
import time
import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)

TICKETS_PER_PAGE = 1000
COMMENTS_PER_PAGE = 100
USERS_SHOW_MANY_BATCH = 100
TICKETS_SHOW_MANY_BATCH = 100

# Rate-limit handling: this client runs inside a Temporal activity thread
# (database_sync_to_async, thread_sensitive=False). Sleeping the full Retry-After
# in-thread ties up a thread-pool slot, so bound both how many times and how long
# we wait before handing the backoff to Temporal's RetryPolicy (which waits between
# activity attempts without holding a thread).
MAX_RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_SLEEP_SECONDS = 30

# Stream attachment bodies in bounded chunks so an oversized file is aborted mid-download
# instead of being fully buffered in the worker's memory before the size check.
ATTACHMENT_CHUNK_BYTES = 64 * 1024

# A Zendesk subdomain is a single DNS label: alphanumerics + hyphens, no leading/trailing
# hyphen, <= 63 chars. Pinning to this stops a crafted subdomain (e.g. "attacker.example#")
# from resolving the base host to something other than "<label>.zendesk.com" (SSRF).
_SUBDOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Zendesk subdomain label.

    Users frequently paste the full host ("nibbles.zendesk.com") or a URL
    ("https://nibbles.zendesk.com/"). Collapse those to the bare label so the base
    URL doesn't become "https://nibbles.zendesk.com.zendesk.com/". Callers still
    validate the result against ``_SUBDOMAIN_LABEL_RE`` before issuing any request.

    Owned here (copied from the warehouse Zendesk source rather than imported) so the
    import's SSRF-sensitive host handling doesn't depend on another product's internals.
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    subdomain = subdomain.split("/", 1)[0]
    return re.sub(r"\.zendesk\.com$", "", subdomain, flags=re.IGNORECASE)


class ZendeskRateLimitError(Exception):
    """Raised when Zendesk keeps rate-limiting beyond the in-thread retry budget.

    Retryable by default, so Temporal's RetryPolicy reschedules the activity and
    absorbs the longer wait out-of-thread.
    """


class ZendeskAttachmentTooLargeError(Exception):
    """Raised when an attachment exceeds the caller's byte cap.

    Distinct from a transport failure so the caller can skip the attachment (count it
    as oversized) without treating it as a retryable download error.
    """


@dataclass(frozen=True)
class ZendeskCredentials:
    subdomain: str
    email_address: str
    api_token: str


class ZendeskImportClient:
    def __init__(self, credentials: ZendeskCredentials) -> None:
        subdomain = normalize_subdomain(credentials.subdomain)
        if not _SUBDOMAIN_LABEL_RE.match(subdomain):
            raise ValueError(f"Invalid Zendesk subdomain: {credentials.subdomain!r}")
        # Pin every request (including absolute next_page / attachment URLs echoed back by
        # the API) to this host so a malicious/compromised API response can't redirect us at
        # internal services.
        self._host = f"{subdomain}.zendesk.com".lower()
        self._base_url = f"https://{self._host}"
        token = base64.b64encode(f"{credentials.email_address}/token:{credentials.api_token}".encode("ascii")).decode(
            "ascii"
        )
        # The Basic auth header carries a reusable Zendesk API token. Mask the token,
        # api_token, and email everywhere they might surface in logged URLs/samples, and
        # disable sample capture entirely since the name-based scrubbers can't guarantee
        # the Authorization header is stripped from captured request samples.
        self._session = make_tracked_session(
            redact_values=(token, credentials.api_token, credentials.email_address),
            capture=False,
        )
        self._headers = {"Authorization": f"Basic {token}"}

    def _handle_rate_limit(self, response: Response, path: str, attempt: int) -> None:
        """Sleep for a bounded Retry-After, or raise once the budget is spent.

        Raising (instead of sleeping indefinitely) hands the backoff to Temporal so a
        long Retry-After can't pin a thread-pool slot for minutes.
        """
        retry_after = int(response.headers.get("Retry-After", "5"))
        if attempt >= MAX_RATE_LIMIT_RETRIES or retry_after > MAX_RATE_LIMIT_SLEEP_SECONDS:
            logger.warning("zendesk_import_rate_limited_giving_up", retry_after=retry_after, path=path, attempt=attempt)
            raise ZendeskRateLimitError(
                f"Zendesk rate limit exceeded in-thread retry budget (Retry-After={retry_after}s, attempt={attempt})"
            )
        logger.warning("zendesk_import_rate_limited", retry_after=retry_after, path=path, attempt=attempt)
        time.sleep(retry_after)

    def _assert_expected_host(self, url: str) -> None:
        """Reject absolute URLs that aren't https on the pinned Zendesk host (SSRF guard).

        Scheme is enforced alongside host: a host-only check lets a malicious/compromised API
        response hand back an http:// URL on the right host, which passes but sends the reusable
        Basic auth token in cleartext over the wire. Zendesk only ever returns https URLs, so
        anything else is rejected.
        """
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme.lower() != "https" or host is None or host.lower() != self._host:
            raise ValueError(f"Refusing to fetch non-https or off-host URL (expected https://{self._host}): {url!r}")

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path.startswith("http"):
            self._assert_expected_host(path)
            url = path
        else:
            url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            response = self._session.request(method, url, headers=self._headers, params=params, timeout=60)
            if response.status_code == 429:
                self._handle_rate_limit(response, path, attempt)
                attempt += 1
                continue
            response.raise_for_status()
            return response.json()

    def list_ticket_ids_page(
        self, *, cursor: str | None = None, start_time: int = 0
    ) -> tuple[list[int], str | None, bool]:
        params: dict[str, Any] = {"per_page": TICKETS_PER_PAGE}
        if cursor:
            params["cursor"] = cursor
        else:
            params["start_time"] = start_time

        data = self._request("GET", "/api/v2/incremental/tickets/cursor", params=params)
        tickets = data.get("tickets") or []
        ticket_ids = [int(t["id"]) for t in tickets if t.get("id") is not None]
        end_of_stream = bool(data.get("end_of_stream"))
        after_cursor = data.get("after_cursor")
        if end_of_stream:
            return ticket_ids, None, True
        if not after_cursor:
            raise ValueError("Zendesk cursor export missing after_cursor before end_of_stream")
        return ticket_ids, str(after_cursor), False

    def fetch_tickets(self, ticket_ids: list[int]) -> list[dict[str, Any]]:
        if not ticket_ids:
            return []
        results: list[dict[str, Any]] = []
        for i in range(0, len(ticket_ids), TICKETS_SHOW_MANY_BATCH):
            batch = ticket_ids[i : i + TICKETS_SHOW_MANY_BATCH]
            data = self._request(
                "GET",
                "/api/v2/tickets/show_many.json",
                params={"ids": ",".join(str(tid) for tid in batch)},
            )
            results.extend(data.get("tickets") or [])
        return results

    def fetch_users(self, user_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not user_ids:
            return {}
        users_by_id: dict[int, dict[str, Any]] = {}
        unique_ids = sorted(set(user_ids))
        for i in range(0, len(unique_ids), USERS_SHOW_MANY_BATCH):
            batch = unique_ids[i : i + USERS_SHOW_MANY_BATCH]
            data = self._request(
                "GET",
                "/api/v2/users/show_many.json",
                params={"ids": ",".join(str(uid) for uid in batch)},
            )
            for user in data.get("users") or []:
                if user.get("id") is not None:
                    users_by_id[int(user["id"])] = user
        return users_by_id

    def fetch_comments(self, ticket_id: int) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        url: str | None = f"/api/v2/tickets/{ticket_id}/comments.json"
        params: dict[str, Any] | None = {"per_page": COMMENTS_PER_PAGE}
        while url:
            data = self._request("GET", url, params=params)
            comments.extend(data.get("comments") or [])
            url = data.get("next_page")
            params = None
        return comments

    def download_attachment(self, content_url: str, *, max_bytes: int) -> bytes:
        self._assert_expected_host(content_url)
        attempt = 0
        while True:
            with self._session.get(content_url, headers=self._headers, timeout=120, stream=True) as response:
                if response.status_code == 429:
                    self._handle_rate_limit(response, content_url, attempt)
                    attempt += 1
                    continue
                response.raise_for_status()
                # Precheck the declared size so a server-advertised oversized body is rejected
                # before we read any of it.
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise ZendeskAttachmentTooLargeError(
                                f"Attachment exceeds {max_bytes} bytes (Content-Length={declared})"
                            )
                    except ValueError:
                        pass
                # A lying/absent Content-Length can't sneak past: abort once streamed bytes
                # cross the cap instead of buffering the whole response.
                buffer = bytearray()
                for chunk in response.iter_content(chunk_size=ATTACHMENT_CHUNK_BYTES):
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise ZendeskAttachmentTooLargeError(f"Attachment exceeds {max_bytes} bytes while streaming")
                return bytes(buffer)


def validate_zendesk_credentials(credentials: ZendeskCredentials) -> bool:
    """Probe the tickets count endpoint to confirm the credentials work.

    Validates the subdomain to a single DNS label here (same guard as
    `ZendeskImportClient.__init__`) so a crafted subdomain like "attacker.example#"
    can't retarget the probe — and the Basic auth token with it — at another host (SSRF).
    """
    subdomain = normalize_subdomain(credentials.subdomain)
    if not _SUBDOMAIN_LABEL_RE.match(subdomain):
        return False
    token = base64.b64encode(f"{credentials.email_address}/token:{credentials.api_token}".encode("ascii")).decode(
        "ascii"
    )
    # The Basic auth header carries a reusable Zendesk API token. Mask the token, api_token,
    # and email in logged URLs/samples, and disable sample capture so the Authorization header
    # can't leak into HTTP telemetry.
    session = make_tracked_session(
        redact_values=(token, credentials.api_token, credentials.email_address),
        capture=False,
    )
    # Runs synchronously inside the settings-page create() request handler. Without a timeout a
    # slow/unresponsive host would pin the Django worker indefinitely; without the try/except a
    # transport-level error (DNS/connection/SSL) would escape as a 500 instead of the intended
    # "credentials rejected" 400. Any failure to reach + authenticate == invalid credentials.
    try:
        res = session.get(
            f"https://{subdomain}.zendesk.com/api/v2/tickets/count",
            headers={"Authorization": f"Basic {token}"},
            timeout=10,
        )
        return res.status_code == 200
    except Exception:
        return False
