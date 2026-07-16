"""Plain GraphQL API client for historical thread import."""

from __future__ import annotations

import time
import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import structlog
from requests import Response
from requests.adapters import HTTPAdapter

from posthog.security.url_validation import validate_url_and_pin_ips

from products.conversations.backend.temporal.plain_import.constants import (
    MESSAGE_ENTRY_TYPES,
    REGION_HOSTS,
    THREADS_PER_PAGE,
    TIMELINE_ENTRIES_PER_PAGE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)

MAX_RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_SLEEP_SECONDS = 30
ATTACHMENT_CHUNK_BYTES = 64 * 1024
# Attachment download URLs point at external object storage that may 3xx to a CDN/bucket edge.
# Follow a small, bounded number of hops, re-validating each one, instead of trusting requests'
# built-in redirect chain (which never re-checks the target host — the classic SSRF bypass).
MAX_ATTACHMENT_REDIRECTS = 3

LIST_THREADS_QUERY = """
query ListThreads($after: String, $first: Int!) {
  threads(
    filters: { isMarkedAsSpam: false }
    first: $first
    after: $after
    sortBy: { field: CREATED_AT, direction: ASC }
  ) {
    edges {
      node {
        id
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

FETCH_THREAD_QUERY = """
query FetchThread($threadId: ID!) {
  thread(threadId: $threadId) {
    id
    ref
    title
    priority
    status
    createdAt {
      iso8601
    }
    customer {
      id
      fullName
      email {
        email
        isVerified
      }
    }
    labels {
      labelType {
        name
      }
    }
    firstInboundMessageInfo {
      messageSource
    }
  }
}
"""

FETCH_TIMELINE_ENTRIES_QUERY = """
query FetchTimelineEntries($threadId: ID!, $after: String, $first: Int!, $entryTypes: [TimelineEntryType!]) {
  thread(threadId: $threadId) {
    timelineEntries(first: $first, after: $after, filters: { entryTypes: $entryTypes }) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        node {
          id
          actor {
            __typename
          }
          timestamp {
            iso8601
          }
          entry {
            __typename
            ... on EmailEntry {
              subject
              fullTextContent
              fullMarkdownContent
              from {
                name
                email
              }
              to {
                name
                email
              }
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on ChatEntry {
              text
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on SlackMessageEntry {
              text
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on SlackReplyEntry {
              text
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on MSTeamsMessageEntry {
              text
              markdownContent
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on DiscordMessageEntry {
              markdownContent
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on NoteEntry {
              text
              markdown
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
            ... on CustomEntry {
              title
              components {
                __typename
                ... on ComponentText {
                  text
                }
                ... on ComponentPlainText {
                  plainText
                }
                ... on ComponentRow {
                  rowMainContent {
                    __typename
                    ... on ComponentText {
                      text
                    }
                    ... on ComponentPlainText {
                      plainText
                    }
                  }
                }
                ... on ComponentContainer {
                  containerContent {
                    __typename
                    ... on ComponentText {
                      text
                    }
                    ... on ComponentPlainText {
                      plainText
                    }
                  }
                }
              }
              attachments {
                id
                fileName
                fileExtension
                fileMimeType
              }
            }
          }
        }
      }
    }
  }
}
"""

CREATE_ATTACHMENT_DOWNLOAD_URL_MUTATION = """
mutation CreateAttachmentDownloadUrl($attachmentId: ID!) {
  createAttachmentDownloadUrl(input: { attachmentId: $attachmentId }) {
    attachmentDownloadUrl {
      downloadUrl
      expiresAt {
        iso8601
      }
    }
    error {
      message
      type
    }
  }
}
"""

VALIDATE_CREDENTIALS_QUERY = """
query ValidateCredentials {
  threads(first: 1) {
    edges {
      node {
        id
      }
    }
  }
}
"""


class PlainRateLimitError(Exception):
    """Raised when Plain keeps rate-limiting beyond the in-thread retry budget."""


class PlainAttachmentTooLargeError(Exception):
    """Raised when an attachment exceeds the caller's byte cap."""


class PlainGraphQLError(Exception):
    """Raised when Plain returns GraphQL errors in the response body."""


@dataclass(frozen=True)
class PlainCredentials:
    api_key: str
    region: str  # "uk" | "us"


class _PinnedIPAdapter(HTTPAdapter):
    """Requests adapter that connects to a pre-validated IP for a given host.

    The attachment host is validated (SSRF policy) and its IP resolved up front;
    pinning the connection to that exact IP closes the DNS-rebinding TOCTOU window
    between validation and connect. TLS SNI / cert verification still use the original
    hostname. Single-use, not thread-safe. Mirrors the shared pattern in
    products/business_knowledge/backend/url_fetch.py.
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
        parsed = urlsplit(request.url or "")
        host = (parsed.hostname or "").lower()
        ip_str = self._pin_map.get(host)
        if ip_str is not None:
            self._current_original_host = host
            ip_netloc = f"[{ip_str}]" if ":" in ip_str else ip_str
            if parsed.port:
                ip_netloc = f"{ip_netloc}:{parsed.port}"
            request.url = urlunsplit((parsed.scheme, ip_netloc, parsed.path, parsed.query, ""))
            original_netloc = f"{host}:{parsed.port}" if parsed.port else host
            if request.headers is not None:
                request.headers["Host"] = original_netloc
        else:
            self._current_original_host = None
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)

    def cert_verify(self, conn: object, url: str, verify: bool | str, cert: None | str | tuple[str, str]) -> None:
        super().cert_verify(conn, url, verify, cert)  # type: ignore[arg-type]
        original = self._current_original_host
        if not original:
            return
        # Mutating urllib3 pool internals so TLS SNI / cert verification use the original hostname,
        # not the pinned IP. These attrs exist at runtime but aren't visible to static checkers.
        if hasattr(conn, "assert_hostname"):
            conn.assert_hostname = original  # type: ignore[attr-defined]  # ty: ignore[invalid-assignment]
        conn_kw = getattr(conn, "conn_kw", None)
        if isinstance(conn_kw, dict):
            conn_kw["server_hostname"] = original


class PlainImportClient:
    def __init__(self, credentials: PlainCredentials) -> None:
        region = credentials.region.lower().strip()
        if region not in REGION_HOSTS:
            raise ValueError(f"Invalid Plain region: {credentials.region!r} (expected 'uk' or 'us')")
        self._host = REGION_HOSTS[region]
        self._base_url = f"https://{self._host}/graphql/v1"
        self._api_key = credentials.api_key
        self._session = make_tracked_session(
            redact_values=(credentials.api_key,),
            capture=False,
        )
        # Separate session for attachment downloads: they go to external object storage (not the
        # pinned API host) and carry no Plain credentials, so they use per-request IP pinning and
        # manual redirect handling rather than the credentialed API session.
        self._download_session = requests.Session()
        self._headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        }

    def _handle_rate_limit(self, response: Response, path: str, attempt: int) -> None:
        try:
            retry_after = int(response.headers.get("Retry-After", "5"))
        except ValueError:
            retry_after = 5
        if attempt >= MAX_RATE_LIMIT_RETRIES or retry_after > MAX_RATE_LIMIT_SLEEP_SECONDS:
            logger.warning("plain_import_rate_limited_giving_up", retry_after=retry_after, path=path, attempt=attempt)
            raise PlainRateLimitError(
                f"Plain rate limit exceeded in-thread retry budget (Retry-After={retry_after}s, attempt={attempt})"
            )
        logger.warning("plain_import_rate_limited", retry_after=retry_after, path=path, attempt=attempt)
        time.sleep(retry_after)

    def _graphql(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        if operation_name is not None:
            payload["operationName"] = operation_name

        attempt = 0
        while True:
            response = self._session.post(
                self._base_url,
                headers=self._headers,
                json=payload,
                timeout=60,
            )
            if response.status_code == 429:
                self._handle_rate_limit(response, self._base_url, attempt)
                attempt += 1
                continue
            response.raise_for_status()
            data = response.json()
            errors = data.get("errors")
            if errors:
                messages = "; ".join(str(e.get("message") or e) for e in errors)
                raise PlainGraphQLError(f"Plain GraphQL error: {messages}")
            result = data.get("data")
            if not isinstance(result, dict):
                raise PlainGraphQLError("Plain GraphQL response missing data")
            return result

    def list_thread_ids_page(self, *, cursor: str | None = None) -> tuple[list[str], str | None, bool]:
        data = self._graphql(
            LIST_THREADS_QUERY,
            variables={"after": cursor, "first": THREADS_PER_PAGE},
            operation_name="ListThreads",
        )
        threads = data.get("threads") or {}
        edges = threads.get("edges") or []
        thread_ids = [str(edge["node"]["id"]) for edge in edges if edge.get("node") and edge["node"].get("id")]
        page_info = threads.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))
        end_cursor = page_info.get("endCursor")
        if not has_next:
            return thread_ids, None, True
        if not end_cursor:
            raise ValueError("Plain threads page missing endCursor while hasNextPage=true")
        return thread_ids, str(end_cursor), False

    def fetch_thread(self, thread_id: str) -> dict[str, Any]:
        data = self._graphql(
            FETCH_THREAD_QUERY,
            variables={"threadId": thread_id},
            operation_name="FetchThread",
        )
        thread = data.get("thread")
        if not isinstance(thread, dict):
            raise PlainGraphQLError(f"Plain thread not found: {thread_id}")
        return thread

    def fetch_timeline_entries(self, thread_id: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            data = self._graphql(
                FETCH_TIMELINE_ENTRIES_QUERY,
                variables={
                    "threadId": thread_id,
                    "after": cursor,
                    "first": TIMELINE_ENTRIES_PER_PAGE,
                    "entryTypes": MESSAGE_ENTRY_TYPES,
                },
                operation_name="FetchTimelineEntries",
            )
            thread = data.get("thread") or {}
            connection = thread.get("timelineEntries") or {}
            for edge in connection.get("edges") or []:
                node = edge.get("node")
                if isinstance(node, dict):
                    entries.append(node)
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            # A missing cursor with hasNextPage=true must not be treated as the end: that would
            # commit a truncated timeline, and the retry skips the thread by plain_thread_id — so
            # the dropped comments/attachments are unrecoverable. Fail loudly so Temporal retries.
            if not cursor:
                raise ValueError(f"Plain timeline pagination hasNextPage=true without endCursor (thread {thread_id})")
        return entries

    def create_attachment_download_url(self, attachment_id: str) -> str:
        data = self._graphql(
            CREATE_ATTACHMENT_DOWNLOAD_URL_MUTATION,
            variables={"attachmentId": attachment_id},
            operation_name="CreateAttachmentDownloadUrl",
        )
        payload = data.get("createAttachmentDownloadUrl") or {}
        error = payload.get("error")
        if error:
            raise PlainGraphQLError(f"Failed to create attachment download URL: {error.get('message') or error}")
        download = payload.get("attachmentDownloadUrl") or {}
        url = download.get("downloadUrl")
        if not url:
            raise PlainGraphQLError(f"Plain returned no downloadUrl for attachment {attachment_id}")
        return str(url)

    def download_attachment(self, attachment_id: str, *, max_bytes: int) -> bytes:
        content_url = self.create_attachment_download_url(attachment_id)
        # The signed URL points at external object storage whose host varies by region/bucket, so
        # it can't be pinned to a fixed host like the API. Enforce the shared SSRF policy on every
        # hop instead: https only, no metadata/internal/private targets, IP-pinned connection, and
        # manual (re-validated) redirect following. Auto-following redirects would let a manipulated
        # response or open redirect steer the worker at an internal HTTPS service.
        current_url = content_url
        for _hop in range(MAX_ATTACHMENT_REDIRECTS + 1):
            parts = urlsplit(current_url)
            if parts.scheme.lower() != "https" or not parts.hostname:
                raise ValueError(f"Refusing to fetch non-https attachment URL: {current_url!r}")

            allowed, reason, pinned_ips = validate_url_and_pin_ips(current_url)
            if not allowed:
                raise ValueError(f"Refusing to fetch attachment URL blocked by SSRF policy: {reason}")

            adapter = _PinnedIPAdapter()
            if pinned_ips:
                adapter.pin(parts.hostname.lower(), next(iter(pinned_ips)))
            self._download_session.mount("https://", adapter)

            attempt = 0
            while True:
                with self._download_session.get(
                    current_url, timeout=120, stream=True, allow_redirects=False
                ) as response:
                    if response.status_code == 429:
                        self._handle_rate_limit(response, current_url, attempt)
                        attempt += 1
                        continue
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("Attachment redirect missing Location header")
                        current_url = urljoin(current_url, location)
                        break  # re-validate + re-pin the new target on the next hop
                    response.raise_for_status()
                    declared = response.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            if int(declared) > max_bytes:
                                raise PlainAttachmentTooLargeError(
                                    f"Attachment exceeds {max_bytes} bytes (Content-Length={declared})"
                                )
                        except ValueError:
                            pass
                    buffer = bytearray()
                    for chunk in response.iter_content(chunk_size=ATTACHMENT_CHUNK_BYTES):
                        if not chunk:
                            continue
                        buffer.extend(chunk)
                        if len(buffer) > max_bytes:
                            raise PlainAttachmentTooLargeError(f"Attachment exceeds {max_bytes} bytes while streaming")
                    return bytes(buffer)

        raise ValueError(f"Attachment exceeded redirect limit ({MAX_ATTACHMENT_REDIRECTS})")


def validate_plain_credentials(credentials: PlainCredentials) -> bool:
    """Probe threads(first:1) to confirm the API key works for the chosen region."""
    region = credentials.region.lower().strip()
    if region not in REGION_HOSTS:
        return False
    host = REGION_HOSTS[region]
    session = make_tracked_session(
        redact_values=(credentials.api_key,),
        capture=False,
    )
    try:
        res = session.post(
            f"https://{host}/graphql/v1",
            headers={
                "Authorization": f"Bearer {credentials.api_key}",
                "Content-Type": "application/json",
            },
            json={"query": VALIDATE_CREDENTIALS_QUERY, "operationName": "ValidateCredentials"},
            timeout=10,
        )
        if res.status_code != 200:
            return False
        data = res.json()
        if data.get("errors"):
            return False
        return isinstance(data.get("data"), dict) and "threads" in (data.get("data") or {})
    except Exception:
        return False
