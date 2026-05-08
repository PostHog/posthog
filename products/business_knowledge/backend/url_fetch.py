"""
SSRF-hardened HTTP fetch for URL-backed knowledge sources.

Responsibilities:
- Validate URL (reuses `posthog.security.url_validation`) before each hop.
- Manual redirect handling — we refuse the default `requests` redirect chain
  because it does *not* re-validate the target IP, which is the classic
  DNS-rebinding / open-redirect bypass for SSRF.
- Stream-read the body with a hard byte cap so a malicious server can't blow
  up process memory by advertising `Content-Length: 0` and then never closing.
- Conditional GET (`If-None-Match`) so repeat refreshes are cheap.
"""

from __future__ import annotations

import hashlib
import urllib.parse as urlparse
from dataclasses import dataclass

import requests
import structlog

from posthog.security.url_validation import is_url_allowed

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
    Core SSRF-hardened GET with manual redirect handling.

    Re-validates `is_url_allowed` on every redirect hop. Stream-reads the
    body with a hard byte cap. Used by both `fetch_url` (content GET with
    conditional ETag) and `fetch_text` (metadata GET for discover).

    Raises `UrlFetchError` with a user-safe message on any failure.
    """

    current = strip_userinfo(normalize_url(url))
    session = requests.Session()
    try:
        for _hop in range(URL_MAX_REDIRECTS + 1):
            allowed, reason = is_url_allowed(current)
            if not allowed:
                logger.warning(
                    "business_knowledge.url_fetch.ssrf_blocked",
                    url=current,
                    reason=reason,
                )
                raise UrlFetchError("URL is not reachable from this environment.")

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
