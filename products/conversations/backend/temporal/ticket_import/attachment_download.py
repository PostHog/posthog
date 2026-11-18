"""Capped download of message attachments for historical ticket imports."""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

import requests

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import UNRESOLVED_HOST_REASON

CHUNK_BYTES = 64 * 1024
MAX_REDIRECTS = 3
MAX_RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_SLEEP_SECONDS = 30
DEFAULT_RATE_LIMIT_SLEEP_SECONDS = 2
MAX_DNS_RETRIES = 2
DNS_RETRY_SLEEP_SECONDS = 2

# requests decodes a compressed body while it streams, so one small chunk can expand far past
# the byte cap before the cap is checked. Ask for the bytes as stored, and refuse a response
# that is encoded anyway.
_REQUEST_HEADERS = {"Accept-Encoding": "identity"}


class AttachmentTooLargeError(Exception):
    """Raised when an attachment exceeds the caller's byte cap, so the caller can skip it."""

    def __init__(self, message: str, *, bytes_read: int = 0) -> None:
        super().__init__(message)
        self.bytes_read = bytes_read


class AttachmentDownloadError(Exception):
    """An attachment download failure whose message leaves out the signed URL.

    Attachment links carry their own access signature, so a requests exception message (which
    embeds the URL) must not reach logs or Temporal failure history.
    """

    def __init__(self, status_code: int | None, *, retry_after: int | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"Attachment download failed (status={status_code})")

    @property
    def retryable(self) -> bool:
        # A transport error has no status. A rate limit or a server error can pass. An expired
        # or deleted link (any other 4xx) won't recover on retry.
        return self.status_code is None or self.status_code == 429 or self.status_code >= 500


@frozen
class DownloadedAttachment:
    content: bytes
    content_type: str


def _retry_after_seconds(response: requests.Response) -> int | None:
    try:
        return int(response.headers.get("Retry-After", ""))
    except ValueError:
        return None


def _download_once(url: str, *, max_bytes: int) -> DownloadedAttachment:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if urlsplit(current).scheme.lower() != "https":
            raise ValueError("Refusing to fetch a non-https attachment URL")
        with pinned_session(current) as session:
            with session.get(
                current, timeout=120, stream=True, allow_redirects=False, headers=_REQUEST_HEADERS
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Attachment redirect without a Location header")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise AttachmentDownloadError(response.status_code, retry_after=_retry_after_seconds(response))
                if (response.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
                    raise ValueError("Refusing an attachment response with a content encoding")
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise AttachmentTooLargeError(
                                f"Attachment exceeds {max_bytes} bytes (Content-Length={declared})"
                            )
                    except ValueError:
                        pass
                buffer = bytearray()
                for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise AttachmentTooLargeError(
                            f"Attachment exceeds {max_bytes} bytes while streaming", bytes_read=len(buffer)
                        )
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                return DownloadedAttachment(content=bytes(buffer), content_type=content_type)
    raise ValueError("Too many attachment redirects")


def download_attachment(url: str, *, max_bytes: int) -> DownloadedAttachment:
    """Download an attachment from a signed link, with a byte cap.

    No Authorization header is sent, so a provider's API token never leaves its API host. Each
    hop (including redirects) goes through pinned_session, which rejects private and internal
    addresses (SSRF).

    A rate-limited download waits in-thread a few times. Skipping the file instead would lose
    it for good, because a later import skips the ticket as already imported.
    """
    rate_limit_attempt = 0
    dns_attempt = 0
    while True:
        try:
            return _download_once(url, max_bytes=max_bytes)
        except requests.RequestException:
            raise AttachmentDownloadError(None) from None
        except SSRFBlockedError as error:
            # pinned_session reports a DNS timeout and a host that does not exist the same way.
            # A timeout passes within seconds, so wait for it here. A host that stays unresolved
            # is treated as gone and its file is skipped, because retrying the batch for it
            # would fail the whole import over one dead link.
            if str(error) != UNRESOLVED_HOST_REASON or dns_attempt >= MAX_DNS_RETRIES:
                raise
            time.sleep(DNS_RETRY_SLEEP_SECONDS)
            dns_attempt += 1
        except AttachmentDownloadError as error:
            wait = DEFAULT_RATE_LIMIT_SLEEP_SECONDS if error.retry_after is None else max(1, error.retry_after)
            if (
                error.status_code != 429
                or rate_limit_attempt >= MAX_RATE_LIMIT_RETRIES
                or wait > MAX_RATE_LIMIT_SLEEP_SECONDS
            ):
                raise
            time.sleep(wait)
            rate_limit_attempt += 1
