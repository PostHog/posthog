"""Zendesk Support API client for historical ticket import."""

from __future__ import annotations

import re
import time
import base64
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urljoin, urlparse, urlsplit, urlunparse

import requests
import structlog
from requests import Response
from requests.adapters import HTTPAdapter

from posthog.security.url_validation import has_authority_bypass_chars, validate_url_and_pin_ips

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

# Attachment content_url lives on the Zendesk host and 302-redirects to an external CDN, so we
# must follow at least one hop. Bound it so a redirect loop can't spin forever.
MAX_ATTACHMENT_REDIRECTS = 5
# The credential probe follows Zendesk's own same-host canonicalization redirects (trailing
# slash, account host-mapping) by hand. Bounded so a redirect loop can't hang the settings request.
MAX_PROBE_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

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


class _PinnedIPAdapter(HTTPAdapter):
    """Requests adapter that connects to a pre-validated IP instead of re-resolving DNS.

    Eliminates the DNS-rebinding TOCTOU window: an off-host attachment redirect is validated
    with ``validate_url_and_pin_ips`` and the resulting IP is pinned here, so the socket goes to
    the exact address the SSRF allowlist checked. TLS SNI + cert verification still use the
    original hostname (via ``assert_hostname`` / ``server_hostname``), not the IP.

    Single-use, not thread-safe — created per off-host download hop.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pin_map: dict[str, str] = {}
        self._current_original_host: str | None = None

    def pin(self, hostname: str, ip: str) -> None:
        self._pin_map[hostname.lower()] = ip

    def send(  # type: ignore[override]
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: None | float | tuple[float, float] = None,
        verify: bool | str = True,
        cert: None | str | tuple[str, str] = None,
        proxies: dict[str, str] | None = None,
    ) -> Response:
        parsed = urlparse(request.url or "")
        host = (parsed.hostname or "").lower()
        ip_str = self._pin_map.get(host)
        if ip_str is not None:
            self._current_original_host = host
            ip_netloc = f"[{ip_str}]" if ":" in ip_str else ip_str
            if parsed.port:
                ip_netloc = f"{ip_netloc}:{parsed.port}"
            request.url = urlunparse((parsed.scheme, ip_netloc, parsed.path, parsed.params, parsed.query, ""))
            original_netloc = f"{host}:{parsed.port}" if parsed.port else host
            if request.headers is not None:
                request.headers["Host"] = original_netloc
        else:
            self._current_original_host = None
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)

    def cert_verify(self, conn: object, url: str, verify: bool | str, cert: None | str | tuple[str, str]) -> None:
        super().cert_verify(conn, url, verify, cert)  # type: ignore[arg-type]
        original = getattr(self, "_current_original_host", None)
        if original:
            # Mutating urllib3 pool internals so TLS SNI/cert checks use the original hostname
            # rather than the pinned IP. These attrs exist at runtime but aren't statically typed,
            # so go through an Any-typed handle to avoid a read-only-property assignment error.
            pool = cast(Any, conn)
            if hasattr(conn, "assert_hostname"):
                pool.assert_hostname = original
            conn_kw = getattr(conn, "conn_kw", None)
            if isinstance(conn_kw, dict):
                conn_kw["server_hostname"] = original


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
        # Pin the base host and validate every URL we're handed (absolute next_page / attachment
        # content_url echoed back by the API) against it. Redirects are the escape hatch: the
        # session never auto-follows (allow_redirects=False), so an HTTP 302 can't silently
        # retarget a token-bearing request at an internal service. The one legitimate redirect
        # (attachment content_url -> CDN) is followed manually with per-hop SSRF validation in
        # download_attachment.
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
            allow_redirects=False,
        )
        self._headers = {"Authorization": f"Basic {token}"}

    def _handle_rate_limit(self, response: Response, path: str, attempt: int) -> None:
        """Sleep for a bounded Retry-After, or raise once the budget is spent.

        Raising (instead of sleeping indefinitely) hands the backoff to Temporal so a
        long Retry-After can't pin a thread-pool slot for minutes.
        """
        try:
            # Retry-After may be an HTTP-date (or garbage) rather than delta-seconds; fall back to a
            # short default instead of letting a ValueError escape mid-backoff.
            retry_after = int(response.headers.get("Retry-After", "5"))
        except ValueError:
            retry_after = 5
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

        A backslash (or %5c) before the ``@`` makes urlsplit read the host after it while
        requests/urllib3 treat the backslash as the authority terminator and connect to the host
        *before* it — so "https://evil.example\\@acme.zendesk.com/" would pass a naive host check
        yet send the token to evil.example. Reject that ambiguity outright.
        """
        if has_authority_bypass_chars(url):
            raise ValueError(f"Refusing to fetch URL with ambiguous authority: {url!r}")
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme.lower() != "https" or host is None or host.lower() != self._host:
            raise ValueError(f"Refusing to fetch non-https or off-host URL (expected https://{self._host}): {url!r}")

    def _offhost_redirect_session(self, url: str) -> requests.Session:
        """Build a single-use session that connects to the SSRF-validated, IP-pinned redirect host.

        ``validate_url_and_pin_ips`` re-resolves and checks the host, and the returned IP is pinned
        onto the adapter so the follow-up GET connects to the exact address we validated. This
        closes the DNS-rebinding TOCTOU: without pinning, ``requests`` would resolve the hostname
        again and an attacker could return a public IP during validation, then rebind to an
        internal/metadata address before the connect.
        """
        allowed, reason, pinned_ips = validate_url_and_pin_ips(url)
        if not allowed:
            raise ValueError(f"Refusing to follow attachment redirect to disallowed host ({reason}): {url!r}")
        adapter = _PinnedIPAdapter()
        hostname = (urlparse(url).hostname or "").lower()
        if pinned_ips:
            adapter.pin(hostname, str(next(iter(pinned_ips))))
        session = requests.Session()
        session.mount("https://", adapter)
        return session

    def _validate_download_redirect(self, url: str) -> tuple[str, requests.Session | None]:
        """Validate an attachment redirect target and pick the session for the next hop.

        Returns (url, session). A hop that stays on the pinned Zendesk host reuses the tracked
        client session and keeps the Basic auth token. An off-host hop (the CDN the content_url
        302s to) must be https and pass the SSRF allowlist (no internal/metadata hosts); it gets a
        fresh IP-pinned session with no auth header, so the reusable Zendesk credential is never
        sent to a host the API response chose and DNS can't be rebound after validation.
        """
        # A backslash/%5c authority-bypass makes urlsplit see the pinned host (keeping the token +
        # tracked session) while requests connects elsewhere — reject before any host comparison.
        if has_authority_bypass_chars(url):
            raise ValueError(f"Refusing to follow attachment redirect with ambiguous authority: {url!r}")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme.lower() != "https":
            raise ValueError(f"Refusing to follow non-https attachment redirect: {url!r}")
        if host == self._host:
            return url, None
        return url, self._offhost_redirect_session(url)

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
            # The API returns JSON directly; a redirect here is anomalous. The session doesn't
            # auto-follow, so refuse it rather than letting a token-bearing request chase an
            # unvalidated Location.
            if response.status_code in _REDIRECT_STATUSES:
                raise ValueError(f"Refusing to follow unexpected redirect from Zendesk API: {path!r}")
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
        # The content_url the API hands us must start on the pinned Zendesk host.
        self._assert_expected_host(content_url)
        url = content_url
        # None => use the tracked client session (on-host, carries the Zendesk token). A non-None
        # value is a fresh IP-pinned, no-auth session for an off-host CDN hop.
        offhost_session: requests.Session | None = None
        attempt = 0
        redirects = 0
        try:
            while True:
                session = offhost_session or self._session
                headers = {} if offhost_session is not None else self._headers
                with session.get(url, headers=headers, timeout=120, stream=True, allow_redirects=False) as response:
                    if response.status_code == 429:
                        self._handle_rate_limit(response, url, attempt)
                        attempt += 1
                        continue
                    # Zendesk 302s the on-host content_url to an external CDN. Follow it by hand
                    # (never auto-follow) so each hop is host/scheme-validated, the Zendesk token is
                    # dropped before any off-host URL, and the validated IP is pinned for the connect.
                    if response.status_code in _REDIRECT_STATUSES:
                        redirects += 1
                        if redirects > MAX_ATTACHMENT_REDIRECTS:
                            raise ValueError(f"Too many redirects while downloading attachment: {content_url!r}")
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError(f"Attachment redirect missing Location: {content_url!r}")
                        next_url, next_session = self._validate_download_redirect(urljoin(url, location))
                        # Close a prior off-host session before replacing it (multi-hop chains).
                        if offhost_session is not None and next_session is not offhost_session:
                            offhost_session.close()
                        url, offhost_session = next_url, next_session
                        attempt = 0
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
                            raise ZendeskAttachmentTooLargeError(
                                f"Attachment exceeds {max_bytes} bytes while streaming"
                            )
                    return bytes(buffer)
        finally:
            if offhost_session is not None:
                offhost_session.close()


def validate_zendesk_credentials(credentials: ZendeskCredentials) -> bool:
    """Probe the tickets count endpoint to confirm the credentials work.

    Validates the subdomain to a single DNS label here (same guard as
    `ZendeskImportClient.__init__`) so a crafted subdomain like "attacker.example#"
    can't retarget the probe — and the Basic auth token with it — at another host (SSRF).
    """
    subdomain = normalize_subdomain(credentials.subdomain)
    if not _SUBDOMAIN_LABEL_RE.match(subdomain):
        return False
    host = f"{subdomain}.zendesk.com".lower()
    token = base64.b64encode(f"{credentials.email_address}/token:{credentials.api_token}".encode("ascii")).decode(
        "ascii"
    )
    # The Basic auth header carries a reusable Zendesk API token. Mask the token, api_token,
    # and email in logged URLs/samples, and disable sample capture so the Authorization header
    # can't leak into HTTP telemetry.
    session = make_tracked_session(
        redact_values=(token, credentials.api_token, credentials.email_address),
        capture=False,
        allow_redirects=False,
    )
    # Runs synchronously inside the settings-page create() request handler. Without a timeout a
    # slow/unresponsive host would pin the Django worker indefinitely; without the try/except a
    # transport-level error (DNS/connection/SSL) would escape as a 500 instead of the intended
    # "credentials rejected" 400. Any failure to reach + authenticate == invalid credentials.
    url = f"https://{host}/api/v2/tickets/count"
    try:
        # Follow Zendesk's own canonicalization redirects (trailing slash, host-mapping) by hand
        # so valid credentials on a redirecting account aren't misreported as invalid. Only same-
        # host https hops are followed — the token never leaves the pinned Zendesk host, and an
        # off-host or cleartext redirect is treated as a failed probe rather than chased.
        for _ in range(MAX_PROBE_REDIRECTS + 1):
            res = session.get(url, headers={"Authorization": f"Basic {token}"}, timeout=10)
            if res.status_code not in _REDIRECT_STATUSES:
                return res.status_code == 200
            location = res.headers.get("Location")
            if not location:
                return False
            nxt = urljoin(url, location)
            # Same authority-bypass guard as the attachment path: a backslash/%5c can make urlsplit
            # read the pinned host while requests connects elsewhere with the token attached.
            if has_authority_bypass_chars(nxt):
                return False
            parts = urlsplit(nxt)
            if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != host:
                return False
            url = nxt
        return False
    except Exception:
        return False
