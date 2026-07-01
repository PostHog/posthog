"""Zendesk Support API client for historical ticket import."""

from __future__ import annotations

import time
import base64
from dataclasses import dataclass
from typing import Any

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import normalize_subdomain

logger = structlog.get_logger(__name__)

TICKETS_PER_PAGE = 1000
COMMENTS_PER_PAGE = 100
USERS_SHOW_MANY_BATCH = 100
TICKETS_SHOW_MANY_BATCH = 100


@dataclass(frozen=True)
class ZendeskCredentials:
    subdomain: str
    email_address: str
    api_token: str


class ZendeskImportClient:
    def __init__(self, credentials: ZendeskCredentials) -> None:
        subdomain = normalize_subdomain(credentials.subdomain)
        self._base_url = f"https://{subdomain}.zendesk.com"
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

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        while True:
            response = self._session.request(method, url, headers=self._headers, params=params, timeout=60)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                logger.warning("zendesk_import_rate_limited", retry_after=retry_after, path=path)
                time.sleep(retry_after)
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

    def download_attachment(self, content_url: str) -> bytes:
        while True:
            response = self._session.get(content_url, headers=self._headers, timeout=120)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.content


def validate_zendesk_credentials(credentials: ZendeskCredentials) -> bool:
    from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import validate_credentials

    return validate_credentials(credentials.subdomain, credentials.api_token, credentials.email_address)
