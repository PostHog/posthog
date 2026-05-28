"""
Thin HTTP client for the agent-janitor service. The Django API uses this to
proxy bundle reads/writes through to the node side, which is the layer that
actually owns BundleStore (FS in dev, S3 in prod).

Auth is a single shared secret carried in `x-internal-secret`. Endpoints are
documented in services/agent-janitor/src/server.ts.

Configured via two env vars:
    AGENT_JANITOR_URL          base URL (default: http://localhost:3031)
    AGENT_JANITOR_SECRET       value sent as `x-internal-secret`
"""

from __future__ import annotations

import os
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class JanitorClientError(Exception):
    """Wraps non-2xx janitor responses + transport failures so view code can
    map them to DRF responses with a single except clause."""

    def __init__(self, status_code: int, message: str, body: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class JanitorClient:
    def __init__(self, base_url: str | None = None, secret: str | None = None, timeout: float = 30.0) -> None:
        # Default matches `bin/mprocs.yaml`'s janitor `PORT=${AGENT_JANITOR_PORT:-3031}`.
        # Keep these two in lockstep — Django + janitor must agree on the URL
        # for the bundle proxy to work in dev without explicit env wiring.
        self.base_url = (base_url or os.environ.get("AGENT_JANITOR_URL") or "http://localhost:3031").rstrip("/")
        self.secret = secret if secret is not None else os.environ.get("AGENT_JANITOR_SECRET", "")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self.secret:
            h["x-internal-secret"] = self.secret
        return h

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(method, url, headers=self._headers(), timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            logger.exception("janitor request failed")
            raise JanitorClientError(502, f"janitor unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise JanitorClientError(resp.status_code, f"janitor returned {resp.status_code}", body=body)
        if not resp.content:
            return {}
        return resp.json()

    # ── revisions ──────────────────────────────────────────────────────────

    def manifest(self, revision_id: str) -> dict:
        return self._call("GET", f"/revisions/{revision_id}/manifest")

    def get_file(self, revision_id: str, path: str) -> dict:
        return self._call("GET", f"/revisions/{revision_id}/file", params={"path": path})

    def put_file(self, revision_id: str, path: str, content: str) -> dict:
        return self._call(
            "PUT",
            f"/revisions/{revision_id}/file",
            params={"path": path},
            json={"content": content},
        )

    def delete_file(self, revision_id: str, path: str) -> dict:
        return self._call("DELETE", f"/revisions/{revision_id}/file", params={"path": path})

    def get_bundle(self, revision_id: str) -> dict:
        return self._call("GET", f"/revisions/{revision_id}/bundle")

    def put_bundle(self, revision_id: str, files: dict[str, str], mode: str = "replace") -> dict:
        return self._call(
            "PUT",
            f"/revisions/{revision_id}/bundle",
            json={"files": files, "mode": mode},
        )

    def freeze(self, revision_id: str) -> dict:
        return self._call("POST", f"/revisions/{revision_id}/freeze")

    def validate(self, revision_id: str) -> dict:
        return self._call("POST", f"/revisions/{revision_id}/validate")

    # ── sessions ───────────────────────────────────────────────────────────

    def list_sessions(
        self,
        application_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        state: str | None = None,
        revision_id: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"application_id": application_id}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if state:
            # Comma-separated list (e.g. "completed,failed"). Pass through
            # verbatim — the janitor parses.
            params["state"] = state
        if revision_id:
            params["revision_id"] = revision_id
        if created_after:
            params["created_after"] = created_after
        if created_before:
            params["created_before"] = created_before
        return self._call("GET", "/sessions", params=params)

    def get_session(self, session_id: str, *, last_n: int | None = None) -> dict:
        params: dict[str, Any] = {}
        if last_n is not None:
            params["last_n"] = last_n
        return self._call("GET", f"/sessions/{session_id}", params=params)

    def clone_from(self, target_revision_id: str, source_revision_id: str) -> dict:
        return self._call(
            "POST",
            f"/revisions/{target_revision_id}/clone_from",
            json={"source_revision_id": source_revision_id},
        )

    # ── catalog ────────────────────────────────────────────────────────────

    def native_tools(self) -> dict:
        return self._call("GET", "/native_tools")


def default_client() -> JanitorClient:
    """One module-level singleton. Tests inject by monkey-patching this."""
    return _CLIENT


_CLIENT = JanitorClient()
