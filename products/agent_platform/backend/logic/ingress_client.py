"""
Thin HTTP client for the agent-ingress service — the LIVE (promoted-revision)
runtime surface behind the `agent-invoke` / `agent-send` / `agent-listen` MCP
tools. Two auth stances:

  - run() / send() forward the CALLER's PAT (`Authorization: Bearer …`) so the
    ingress `posthog` auth mode re-introspects it and the session principal is
    the real caller — preserving ACL on later send/listen. See
    services/agent-ingress/src/enqueue/auth.ts.
  - session_digest() is an internal read RPC: a short-lived aud=`agent-ingress.rpc`
    JWT sent as `x-internal-secret`, the same idiom the janitor client uses.

Base URL comes from the `AGENT_INGRESS_URL` env var (default
http://localhost:3030), matching the preview-proxy in presentation/views.py.
"""

from __future__ import annotations

import os
import logging
from datetime import timedelta
from typing import Any

from django.conf import settings

import requests

from posthog.security.outbound_proxy import internal_requests

from .internal_jwt import AgentInternalAudience, encode_agent_internal_jwt

logger = logging.getLogger(__name__)


class IngressClientError(Exception):
    """Wraps non-2xx ingress responses + transport failures so view code can
    map them to DRF responses with a single except clause (mirrors
    JanitorClientError)."""

    def __init__(self, status_code: int, message: str, body: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class IngressClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        # Same source as the preview-proxy (presentation/views.py): the
        # `AGENT_INGRESS_URL` env var, default http://localhost:3030.
        self.base_url = (base_url or os.environ.get("AGENT_INGRESS_URL", "http://localhost:3030")).rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, *, headers: dict[str, str], **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            # In-cluster service — the internal session bypasses HTTP(S)_PROXY
            # (smokescreen blocks private IPs → 407), same as janitor_client.
            resp = internal_requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            logger.exception("ingress request failed")
            raise IngressClientError(502, f"ingress unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise IngressClientError(resp.status_code, f"ingress returned {resp.status_code}", body=body)
        if not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _forward_headers(authorization: str | None) -> dict[str, str]:
        # Forward the caller's PAT verbatim: ingress's `posthog` auth mode
        # re-introspects it so the session principal is the real caller.
        h = {"content-type": "application/json"}
        if authorization:
            h["authorization"] = authorization
        return h

    @staticmethod
    def _internal_headers() -> dict[str, str]:
        h = {"content-type": "application/json"}
        if settings.AGENT_INTERNAL_SIGNING_KEY:
            token = encode_agent_internal_jwt(
                {"sub": "django"},
                timedelta(seconds=60),
                AgentInternalAudience.INGRESS_RPC,
            )
            h["x-internal-secret"] = token
        return h

    # ── LIVE public routes: forward the caller PAT ───────────────────────────

    def run(self, slug: str, *, message: str, external_key: str | None, authorization: str | None) -> dict:
        body: dict[str, Any] = {"message": message}
        if external_key:
            body["external_key"] = external_key
        return self._call("POST", f"/agents/{slug}/run", headers=self._forward_headers(authorization), json=body)

    def send(self, slug: str, *, session_id: str, message: str, authorization: str | None) -> dict:
        return self._call(
            "POST",
            f"/agents/{slug}/send",
            headers=self._forward_headers(authorization),
            json={"session_id": session_id, "message": message},
        )

    # ── internal read RPC: session digest ────────────────────────────────────

    def session_digest(
        self, *, application_id: str, session_id: str, cursor: int | None, max_chars: int | None
    ) -> dict:
        body: dict[str, Any] = {"application_id": application_id, "session_id": session_id}
        if cursor is not None:
            body["cursor"] = cursor
        if max_chars is not None:
            body["max_chars"] = max_chars
        return self._call("POST", "/internal/session-digest", headers=self._internal_headers(), json=body)
