"""
Thin HTTP client for the ai-gateway billing read plane.

Talks to `cmd/billing` over an internal shared secret carried in
`x-internal-secret`. Surfaces:

    GET /v1/wallet?team_id=<id>
    GET /v1/ledger?team_id=<id>&limit=&cursor=&transaction_type=&reference_id_prefix=

These reads are admin/introspection only — the runner keeps using the
gateway data plane's phc_-bearer `/v1/usage/{id}` + `/v1/wallet/balance`
endpoints (see services/agent-shared/src/runtime/gateway-client.ts).

No retry loop here: these are user-driven reads from Django, not the
runner's settle-window probe — a 404 means "not found", full stop.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

import requests

logger = logging.getLogger(__name__)


class BillingClientError(Exception):
    """Wraps non-2xx billing responses + transport failures so view code
    can map them to DRF responses with a single except clause."""

    def __init__(self, status_code: int, message: str, body: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class BillingMisconfigured(BillingClientError):
    """Raised when AI_GATEWAY_BILLING_INTERNAL_SECRET is unset. Lets the
    viewset return a clean 503 rather than firing a no-auth call that
    billing would reject as 401."""

    def __init__(self) -> None:
        super().__init__(503, "ai_gateway billing client is not configured")


class BillingClient:
    """Synchronous httpx-style wrapper. Construct once per request via
    `BillingClient.from_settings()`."""

    def __init__(self, base_url: str, internal_secret: str, timeout: float = 3.0) -> None:
        if not internal_secret:
            raise BillingMisconfigured()
        self.base_url = base_url.rstrip("/")
        self.internal_secret = internal_secret
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> BillingClient:
        return cls(
            base_url=settings.AI_GATEWAY_BILLING_URL,
            internal_secret=settings.AI_GATEWAY_BILLING_INTERNAL_SECRET,
        )

    def _headers(self) -> dict[str, str]:
        return {"x-internal-secret": self.internal_secret, "content-type": "application/json"}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
        except requests.RequestException as e:
            logger.exception("ai-gateway billing request failed", extra={"path": path})
            raise BillingClientError(502, f"billing unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise BillingClientError(resp.status_code, f"billing returned {resp.status_code}", body=body)
        if not resp.content:
            return {}
        return resp.json()

    def wallet(self, team_id: int) -> dict:
        return self._get("/v1/wallet", params={"team_id": team_id})

    def ledger(
        self,
        team_id: int,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        transaction_type: str | None = None,
        reference_id_prefix: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"team_id": team_id}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        if transaction_type is not None:
            params["transaction_type"] = transaction_type
        if reference_id_prefix is not None:
            params["reference_id_prefix"] = reference_id_prefix
        return self._get("/v1/ledger", params=params)
