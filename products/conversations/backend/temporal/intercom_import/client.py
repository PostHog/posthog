"""Intercom REST API client for historical conversation import."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import structlog
from requests import Response

from posthog.security.pinned_requests import pinned_session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)

# Pinned so a workspace-level default version change in Intercom can't silently reshape payloads.
# 2.18 is the first version that paginates conversation parts; older versions return only the 500
# most recent parts, which silently drops the start of long conversations.
INTERCOM_API_VERSION = "2.18"
# Documented maximum for list endpoints.
CONVERSATIONS_PER_PAGE = 150
# Documented maximum for conversation parts per page.
PARTS_PER_PAGE = 500
# Safety stop for a runaway pagination loop (MAX_PART_PAGES * PARTS_PER_PAGE parts).
MAX_PART_PAGES = 100

REGION_HOSTS: dict[str, str] = {
    "us": "api.intercom.io",
    "eu": "api.eu.intercom.io",
    "au": "api.au.intercom.io",
}

# Same in-thread budget as the Zendesk client: this runs inside a Temporal activity thread, so a
# long wait is handed to Temporal's RetryPolicy instead of pinning a thread-pool slot.
MAX_RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_SLEEP_SECONDS = 30
DEFAULT_RATE_LIMIT_SLEEP_SECONDS = 10

_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
_CONTACT_LINK_RE = re.compile(r"/contacts/([A-Za-z0-9]+)")

ATTACHMENT_CHUNK_BYTES = 64 * 1024
MAX_ATTACHMENT_REDIRECTS = 3


class IntercomRateLimitError(Exception):
    """Raised when Intercom keeps rate-limiting beyond the in-thread retry budget.

    Retryable by default, so Temporal's RetryPolicy reschedules the activity.
    """


class IntercomAttachmentTooLargeError(Exception):
    """Raised when an attachment exceeds the caller's byte cap, so the caller can skip it."""


@dataclass(frozen=True)
class IntercomCredentials:
    region: str
    access_token: str = field(repr=False)


def api_host_for_region(region: str) -> str:
    host = REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown Intercom region: {region!r}")
    return host


def _next_cursor(pages: dict[str, Any]) -> str | None:
    # The list docs show `next` as {"page", "starting_after"}, while the shared pages model describes
    # it as a link. Accept both so a shape change can't silently end the listing after one page.
    next_page = pages.get("next")
    if isinstance(next_page, dict):
        cursor = next_page.get("starting_after")
    elif isinstance(next_page, str):
        values = parse_qs(urlsplit(next_page).query).get("starting_after")
        cursor = values[0] if values else None
    else:
        cursor = None
    return str(cursor) if cursor else None


def _has_more_parts(container: dict[str, Any], page: int) -> bool:
    page_parts = container.get("conversation_parts") or []
    if not page_parts:
        return False
    # The docs note some lists omit `next`, so compare the page with total_pages instead.
    total_pages = (container.get("pages") or {}).get("total_pages")
    if isinstance(total_pages, int):
        return page < total_pages
    return len(page_parts) >= PARTS_PER_PAGE


def _validate_id(kind: str, value: str) -> None:
    # Ids come from Intercom's own responses, but they're interpolated into the path, so keep them
    # to the ASCII alphanumerics Intercom uses.
    if not _ID_RE.match(value):
        raise ValueError(f"Invalid Intercom {kind} id: {value!r}")


def _rate_limit_sleep_seconds(response: Response) -> int:
    # Intercom documents X-RateLimit-Reset as a unix timestamp for the end of the current
    # 10-second window, and notes that not every 429 carries it.
    reset = response.headers.get("X-RateLimit-Reset")
    if reset is None:
        return DEFAULT_RATE_LIMIT_SLEEP_SECONDS
    try:
        return max(1, int(reset) - int(time.time()))
    except ValueError:
        return DEFAULT_RATE_LIMIT_SLEEP_SECONDS


class IntercomImportClient:
    def __init__(self, credentials: IntercomCredentials) -> None:
        self._host = api_host_for_region(credentials.region)
        self._base_url = f"https://{self._host}"
        # The bearer token is a reusable workspace credential. Mask it in logged URLs/samples and
        # disable sample capture so the Authorization header can't leak into HTTP telemetry.
        self._session = make_tracked_session(redact_values=(credentials.access_token,), capture=False)
        self._headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Accept": "application/json",
            "Intercom-Version": INTERCOM_API_VERSION,
        }

    def _handle_rate_limit(self, response: Response, path: str, attempt: int) -> None:
        sleep_seconds = _rate_limit_sleep_seconds(response)
        if attempt >= MAX_RATE_LIMIT_RETRIES or sleep_seconds > MAX_RATE_LIMIT_SLEEP_SECONDS:
            logger.warning("intercom_import_rate_limited_giving_up", sleep=sleep_seconds, path=path, attempt=attempt)
            raise IntercomRateLimitError(
                f"Intercom rate limit exceeded in-thread retry budget (sleep={sleep_seconds}s, attempt={attempt})"
            )
        logger.warning("intercom_import_rate_limited", sleep=sleep_seconds, path=path, attempt=attempt)
        time.sleep(sleep_seconds)

    def _send(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Response:
        # Only ever relative paths: the token is never sent anywhere but the pinned regional host.
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            response = self._session.request(method, url, headers=self._headers, params=params, timeout=60)
            if response.status_code != 429:
                return response
            self._handle_rate_limit(response, path, attempt)
            attempt += 1

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._send(method, path, params=params)
        response.raise_for_status()
        return response.json()

    def list_conversation_ids_page(self, *, cursor: str | None = None) -> tuple[list[str], str | None]:
        """Return one page of conversation ids and the cursor for the next page (None at the end)."""
        params: dict[str, Any] = {"per_page": CONVERSATIONS_PER_PAGE}
        if cursor:
            params["starting_after"] = cursor
        data = self._request("GET", "/conversations", params=params)
        conversations = data.get("conversations") or []
        ids = [str(c["id"]) for c in conversations if c.get("id") is not None]
        return ids, _next_cursor(data.get("pages") or {})

    def fetch_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Fetch a conversation with every part, oldest first.

        Sending `page` switches the parts list to oldest-first pagination; without it Intercom
        returns only the 500 most recent parts. Each page repeats the conversation object, so the
        first one is kept and the later pages only contribute parts.
        """
        _validate_id("conversation", conversation_id)
        path = f"/conversations/{conversation_id}"
        conversation = self._request("GET", path, params=self._parts_page_params(1))
        container = conversation.get("conversation_parts") or {}
        parts = list(container.get("conversation_parts") or [])
        page = 1
        while _has_more_parts(container, page):
            if page >= MAX_PART_PAGES:
                logger.warning(
                    "intercom_import_conversation_parts_page_cap",
                    intercom_conversation_id=conversation_id,
                    max_pages=MAX_PART_PAGES,
                )
                break
            page += 1
            container = self._request("GET", path, params=self._parts_page_params(page)).get("conversation_parts") or {}
            parts.extend(container.get("conversation_parts") or [])
        conversation["conversation_parts"] = {"type": "conversation_part.list", "conversation_parts": parts}
        return conversation

    @staticmethod
    def _parts_page_params(page: int) -> dict[str, Any]:
        return {"display_as": "plaintext", "page": page, "per_page": PARTS_PER_PAGE}

    def fetch_contact(self, contact_id: str) -> dict[str, Any]:
        """Fetch a contact with unescaped name and email.

        The contacts endpoint HTML-escapes identity fields unless `escape_identity=false` is sent.
        A merged contact answers 410 Gone with a Link header naming the contact it was merged
        into, which is followed once.
        """
        params = {"escape_identity": "false"}
        _validate_id("contact", contact_id)
        response = self._send("GET", f"/contacts/{contact_id}", params=params)
        if response.status_code == 410:
            merged_into = _CONTACT_LINK_RE.search(response.headers.get("Link") or "")
            if merged_into:
                return self._request("GET", f"/contacts/{merged_into.group(1)}", params=params)
        response.raise_for_status()
        return response.json()

    def download_attachment(self, url: str, *, max_bytes: int) -> bytes:
        """Download an attachment from Intercom's CDN with a byte cap.

        Intercom attachment URLs are signed links that need no Authorization header, so none is
        sent: the workspace token must never leave the API host. Messenger uploads expire 30
        minutes after the conversation was fetched, so callers download right after fetching. Each hop (including redirects) goes
        through pinned_session, which rejects private/internal addresses (SSRF).
        """
        current = url
        for _ in range(MAX_ATTACHMENT_REDIRECTS + 1):
            if urlsplit(current).scheme.lower() != "https":
                raise ValueError(f"Refusing to fetch non-https attachment URL: {current!r}")
            with pinned_session(current) as session:
                with session.get(current, timeout=120, stream=True, allow_redirects=False) as response:
                    if response.is_redirect:
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("Attachment redirect without a Location header")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            if int(declared) > max_bytes:
                                raise IntercomAttachmentTooLargeError(
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
                            raise IntercomAttachmentTooLargeError(
                                f"Attachment exceeds {max_bytes} bytes while streaming"
                            )
                    return bytes(buffer)
        raise ValueError("Too many attachment redirects")


def validate_intercom_credentials(credentials: IntercomCredentials) -> bool:
    """Probe the conversations list to confirm the token works and can read conversations.

    /me would succeed for a token without conversation access, and the import would then fail
    later in the background. Runs synchronously inside the settings-page create() request handler, so it has a short
    timeout and treats any failure to reach + authenticate as invalid credentials.
    """
    try:
        host = api_host_for_region(credentials.region)
    except ValueError:
        return False
    session = make_tracked_session(redact_values=(credentials.access_token,), capture=False)
    try:
        res = session.get(
            f"https://{host}/conversations",
            params={"per_page": 1},
            headers={
                "Authorization": f"Bearer {credentials.access_token}",
                "Accept": "application/json",
                "Intercom-Version": INTERCOM_API_VERSION,
            },
            timeout=10,
        )
        return res.status_code == 200
    except Exception:
        return False
