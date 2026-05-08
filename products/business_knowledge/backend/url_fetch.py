"""
SSRF-hardened HTTP fetch for URL-backed knowledge sources.

Responsibilities:
- Validate URL (reuses `posthog.security.url_validation`) before each hop.
- Pin validated IPs so ``requests`` connects to the exact IPs we checked,
  eliminating the DNS-rebinding TOCTOU window.
- Manual redirect handling — we refuse the default `requests` redirect chain
  because it does *not* re-validate the target IP, which is the classic
  DNS-rebinding / open-redirect bypass for SSRF.
- Stream-read the body with a hard byte cap so a malicious server can't blow
  up process memory by advertising `Content-Length: 0` and then never closing.
- Conditional GET (`If-None-Match`) so repeat refreshes are cheap.
"""

from __future__ import annotations

import hashlib
import ipaddress
import urllib.parse as urlparse
from dataclasses import dataclass

import requests
import structlog
from requests.adapters import HTTPAdapter

from posthog.security.url_validation import validate_url_and_pin_ips

from .constants import URL_CONNECT_TIMEOUT, URL_MAX_BYTES, URL_MAX_REDIRECTS, URL_READ_TIMEOUT, URL_USER_AGENT

logger = structlog.get_logger(__name__)


class UrlFetchError(Exception):
    """Generic fetch failure. Message is user-safe (no internal detail)."""


@dataclass(frozen=True)
class FetchResult:
    status: int  # 200 on success, 304 on Not Modified
    body: bytes | None  # None on 304
    content_type: str | None
    etag: str | None
    final_url: str


def strip_userinfo(url: str) -> str:
    """
    Remove `user:pass@` from authority. Userinfo in URLs is a known SSRF
    smuggling vector (some libraries interpret it as the host when stricter
    parsers don't).
    """

    parsed = urlparse.urlparse(url)
    if parsed.username is None and parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlparse.urlunparse(parsed._replace(netloc=netloc))


def normalize_url(raw: str) -> str:
    """
    Canonicalize a user-submitted URL before validating or storing it.

    Intentionally minimal: strip userinfo + fragment, lowercase the scheme
    and host. We do NOT touch the path/query — a lot of docs sites care about
    trailing slashes and case in path segments.
    """

    raw = raw.strip()
    parsed = urlparse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise UrlFetchError("Invalid URL.")
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlFetchError("Invalid URL.")
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlparse.urlunparse((scheme, netloc, parsed.path, parsed.params, parsed.query, ""))


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- DNS-pinning adapter — eliminates TOCTOU rebinding window ----------------


class _PinnedIPAdapter(HTTPAdapter):
    """
    Requests adapter that rewrites URLs to connect to pre-validated IPs,
    preventing DNS rebinding between validation and connection.

    For HTTPS, sets ``assert_hostname`` and ``server_hostname`` on the
    connection pool so TLS SNI and certificate verification use the
    original hostname (not the IP).

    NOT thread-safe — designed for single-use sessions in ``_ssrf_safe_get``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pin_map: dict[str, str] = {}
        self._current_original_host: str | None = None

    def pin(self, hostname: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        self._pin_map[hostname.lower()] = str(ip)

    def send(  # type: ignore[override]
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: None | float | tuple[float, float] = None,
        verify: bool | str = True,
        cert: None | str | tuple[str, str] = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Response:
        parsed = urlparse.urlparse(request.url or "")
        host = (parsed.hostname or "").lower()
        ip_str = self._pin_map.get(host)

        if ip_str is not None:
            self._current_original_host = host

            ip_netloc = f"[{ip_str}]" if ":" in ip_str else ip_str
            if parsed.port:
                ip_netloc = f"{ip_netloc}:{parsed.port}"

            request.url = urlparse.urlunparse((parsed.scheme, ip_netloc, parsed.path, parsed.params, parsed.query, ""))

            original_netloc = host
            if parsed.port:
                original_netloc = f"{host}:{parsed.port}"
            if request.headers is not None:
                request.headers["Host"] = original_netloc
        else:
            self._current_original_host = None

        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)

    def cert_verify(self, conn: object, url: str, verify: bool | str, cert: None | str | tuple[str, str]) -> None:
        super().cert_verify(conn, url, verify, cert)
        original = getattr(self, "_current_original_host", None)
        if original:
            # We mutate urllib3 pool internals intentionally — these attributes
            # exist at runtime (verified against urllib3 2.6.3) but aren't
            # visible to static type checkers.
            if hasattr(conn, "assert_hostname"):
                conn.assert_hostname = original  # ty: ignore[invalid-assignment]
            # Inject server_hostname into conn_kw so newly created connections
            # use the original hostname for TLS SNI (not the rewritten IP).
            # urllib3 passes **conn_kw to ConnectionCls.__init__, and
            # HTTPSConnection.connect() reads self.server_hostname for SNI.
            if hasattr(conn, "conn_kw") and isinstance(getattr(conn, "conn_kw", None), dict):
                conn.conn_kw["server_hostname"] = original  # ty: ignore[invalid-assignment]


# --- Shared SSRF-safe fetch core ---------------------------------------------


def _read_capped(response: requests.Response, cap: int) -> bytes:
    """Stream the body into memory but abort as soon as we cross `cap` bytes."""

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > cap:
            raise UrlFetchError("Remote response exceeds the maximum allowed size.")
        chunks.append(chunk)
    return b"".join(chunks)


def _ssrf_safe_get(
    url: str,
    *,
    headers: dict[str, str],
    max_bytes: int = URL_MAX_BYTES,
    etag: str | None = None,
) -> FetchResult:
    """
    Core SSRF-hardened GET with manual redirect handling and DNS pinning.

    Re-validates ``validate_url_and_pin_ips`` on every redirect hop and
    pins the validated IPs so ``requests`` connects to the exact addresses
    we checked (no DNS rebinding window). Stream-reads the body with a
    hard byte cap.

    Raises ``UrlFetchError`` with a user-safe message on any failure.
    """

    current = strip_userinfo(normalize_url(url))
    adapter = _PinnedIPAdapter()
    session = requests.Session()
    session.mount(
        "http://", adapter
    )  # nosemgrep: request-session-with-http -- covers both schemes for redirect chains; per-hop validate_url_and_pin_ips enforces safety
    session.mount("https://", adapter)
    try:
        for _hop in range(URL_MAX_REDIRECTS + 1):
            allowed, reason, pinned_ips = validate_url_and_pin_ips(current)
            if not allowed:
                logger.warning(
                    "business_knowledge.url_fetch.ssrf_blocked",
                    url=current,
                    reason=reason,
                )
                raise UrlFetchError("URL is not reachable from this environment.")

            # Pin the first validated IP so requests connects to it directly
            parsed = urlparse.urlparse(current)
            hostname = (parsed.hostname or "").lower()
            if pinned_ips:
                adapter.pin(hostname, next(iter(pinned_ips)))

            merged_headers = dict(headers)
            if etag:
                merged_headers["If-None-Match"] = etag

            try:
                response = session.get(
                    current,
                    headers=merged_headers,
                    timeout=(URL_CONNECT_TIMEOUT, URL_READ_TIMEOUT),
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                logger.info(
                    "business_knowledge.url_fetch.transport_error",
                    url=current,
                    error_type=type(exc).__name__,
                )
                raise UrlFetchError("Failed to fetch the URL.") from exc

            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise UrlFetchError("Redirect without Location header.")
                    next_url = strip_userinfo(urlparse.urljoin(current, location))
                    current = normalize_url(next_url)
                    continue

                if response.status_code == 304:
                    return FetchResult(
                        status=304,
                        body=None,
                        content_type=response.headers.get("Content-Type"),
                        etag=response.headers.get("ETag") or etag,
                        final_url=current,
                    )

                if response.status_code >= 400:
                    raise UrlFetchError(f"Remote responded with status {response.status_code}.")

                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise UrlFetchError("Remote response exceeds the maximum allowed size.")

                body = _read_capped(response, max_bytes)
                return FetchResult(
                    status=200,
                    body=body,
                    content_type=response.headers.get("Content-Type"),
                    etag=response.headers.get("ETag"),
                    final_url=current,
                )
            finally:
                response.close()

        raise UrlFetchError("Too many redirects.")
    finally:
        session.close()


# --- Public API ---------------------------------------------------------------


_CONTENT_HEADERS = {
    "User-Agent": URL_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    "Accept-Language": "en;q=0.9,*;q=0.5",
}

_METADATA_HEADERS = {
    "User-Agent": URL_USER_AGENT,
    "Accept": "application/xml,text/xml,text/html;q=0.9,text/plain;q=0.5,*/*;q=0.1",
}


def fetch_url(url: str, *, etag: str | None = None) -> FetchResult:
    """
    Fetch `url` with SSRF re-validation on every redirect hop.

    Raises `UrlFetchError` with a user-safe message on any failure.
    """

    return _ssrf_safe_get(url, headers=_CONTENT_HEADERS, etag=etag)


def fetch_text(url: str, *, max_bytes: int = URL_MAX_BYTES) -> str:
    """
    SSRF-safe GET returning decoded text. Used by discover for machine-readable
    metadata (sitemap.xml, robots.txt, HTML for link extraction).

    Raises `UrlFetchError` on failure.
    """

    result = _ssrf_safe_get(url, headers=_METADATA_HEADERS, max_bytes=max_bytes)
    if result.body is None:
        return ""
    return result.body.decode("utf-8", errors="replace")


def is_html_content_type(content_type: str | None) -> bool:
    if not content_type:
        # Missing header — trafilatura can still do something sensible with
        # raw HTML, and we fall back to bs4 if it can't.
        return True
    lowered = content_type.split(";", 1)[0].strip().lower()
    return lowered in {"text/html", "application/xhtml+xml", "text/plain"}
