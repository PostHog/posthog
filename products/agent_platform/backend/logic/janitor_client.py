"""
Thin HTTP client for the agent-janitor service. The Django API uses this to
proxy bundle reads/writes through to the node side, which is the layer that
actually owns BundleStore (FS in dev, S3 in prod).

Auth is a short-lived, audience-bound HS256 JWT minted per call and sent as
`x-internal-secret`. Signed with `settings.AGENT_INTERNAL_SIGNING_KEY` (the
same key Django uses for ingress preview tokens, scoped by `aud`). Endpoints
are documented in services/agent-janitor/src/server.ts.

Base URL comes from `settings.AGENT_JANITOR_BASE_URL` (env var of the same
name, default http://localhost:3031).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings

import requests

from posthog.security.outbound_proxy import internal_requests

from .internal_jwt import AgentInternalAudience, encode_agent_internal_jwt

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
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        # Single source of truth: `settings.AGENT_JANITOR_BASE_URL` (default
        # http://localhost:3031, matching `bin/mprocs.yaml`'s janitor PORT).
        # Django + janitor must agree on the URL for the bundle proxy to work.
        self.base_url = (base_url or settings.AGENT_JANITOR_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if settings.AGENT_INTERNAL_SIGNING_KEY:
            token = encode_agent_internal_jwt(
                {"sub": "django"},
                timedelta(seconds=60),
                AgentInternalAudience.JANITOR_RPC,
            )
            h["x-internal-secret"] = token
        return h

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            # The janitor is an in-cluster service — use the internal session so the
            # call bypasses HTTP(S)_PROXY (smokescreen blocks private IPs → 407).
            resp = internal_requests.request(method, url, headers=self._headers(), timeout=self.timeout, **kwargs)
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

    def slack_manifest(self, revision_id: str, *, events_url: str | None, interactivity_url: str | None) -> dict:
        params: dict[str, str] = {}
        if events_url:
            params["events_url"] = events_url
        if interactivity_url:
            params["interactivity_url"] = interactivity_url
        return self._call("GET", f"/revisions/{revision_id}/slack-manifest", params=params)

    # ── typed bundle authoring API ─────────────────────────────────────────
    # The legacy file-grain methods (get_file / put_file / delete_file /
    # put_bundle with mode) were removed; authors now write typed resources
    # (agent_md, skills/<id>, tools/<id>) and the janitor translates to
    # canonical S3 paths under the hood.

    def get_bundle(self, revision_id: str) -> dict:
        """Read the full typed bundle: { agent_md, skills, tools, spec }."""
        return self._call("GET", f"/revisions/{revision_id}/bundle")

    def put_bundle(self, revision_id: str, bundle: dict) -> dict:
        """Full-replace the typed bundle. `bundle` carries agent_md, skills,
        tools, spec — resources NOT in the payload are deleted."""
        return self._call("PUT", f"/revisions/{revision_id}/bundle", json=bundle)

    def put_agent_md(self, revision_id: str, content: str) -> dict:
        return self._call("PUT", f"/revisions/{revision_id}/agent_md", json={"content": content})

    def put_spec(self, revision_id: str, spec: dict) -> dict:
        """Replace the author-facing spec slice (no skills[] / tools[])."""
        return self._call("PUT", f"/revisions/{revision_id}/spec", json={"spec": spec})

    def put_skill(self, revision_id: str, skill_id: str, skill: dict) -> dict:
        """Upsert one skill. `skill` carries { description, body }; stored at skills/<id>/SKILL.md."""
        return self._call("PUT", f"/revisions/{revision_id}/skills/{skill_id}", json=skill)

    def delete_skill(self, revision_id: str, skill_id: str) -> dict:
        return self._call("DELETE", f"/revisions/{revision_id}/skills/{skill_id}")

    def put_tool(self, revision_id: str, tool_id: str, tool: dict) -> dict:
        """Upsert one tool. Triggers AST shape check + esbuild compile on
        the janitor side. `tool` carries { description, args_schema, source }."""
        return self._call("PUT", f"/revisions/{revision_id}/tools/{tool_id}", json=tool)

    def delete_tool(self, revision_id: str, tool_id: str) -> dict:
        return self._call("DELETE", f"/revisions/{revision_id}/tools/{tool_id}")

    def dry_run_tool(self, revision_id: str, tool_id: str, body: dict) -> dict:
        """Single-shot sandbox execution of the persisted compiled.js with
        synthetic args + mock secrets. `body` carries { args, mock_secrets? }."""
        return self._call("POST", f"/revisions/{revision_id}/tools/{tool_id}/dry_run", json=body)

    def freeze(self, revision_id: str) -> dict:
        return self._call("POST", f"/revisions/{revision_id}/freeze")

    def validate(self, revision_id: str) -> dict:
        return self._call("POST", f"/revisions/{revision_id}/validate")

    def cron_fire(self, revision_id: str, *, cron_name: str, request_id: str | None = None) -> dict:
        """Manually fire one cron job, bypassing the scheduler's window logic.

        Same execution path a scheduled firing walks — authoring surface so
        the user can iterate on a cron prompt without waiting for the next
        real firing. `request_id` makes repeat clicks idempotent (the
        janitor uses `cron-manual:<rev>:<name>:<request_id>` as the dedupe
        key); pass a stable id per logical click. Plan §9 "Manual fire."
        """
        body: dict[str, str] = {"cron_name": cron_name}
        if request_id is not None:
            body["request_id"] = request_id
        return self._call("POST", f"/revisions/{revision_id}/cron/fire", json=body)

    def get_system_prompt(self, revision_id: str) -> dict:
        """Return the fully-assembled system prompt for a revision.

        The runner builds this same prompt at session start — framework
        preamble + agent.md + skills index. Authoring tools surface it so
        the author can inspect what the model will actually see.
        """
        return self._call("GET", f"/revisions/{revision_id}/system-prompt")

    # ── sessions ───────────────────────────────────────────────────────────

    def list_sessions(
        self,
        application_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        state: str | None = None,
        revision_id: str | None = None,
        agent_user_id: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        search: str | None = None,
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
        if agent_user_id:
            params["agent_user_id"] = agent_user_id
        if created_after:
            params["created_after"] = created_after
        if created_before:
            params["created_before"] = created_before
        if search:
            params["search"] = search
        return self._call("GET", "/sessions", params=params)

    def get_session(self, session_id: str, *, last_n: int | None = None) -> dict:
        params: dict[str, Any] = {}
        if last_n is not None:
            params["last_n"] = last_n
        return self._call("GET", f"/sessions/{session_id}", params=params)

    # ── fleet stats ────────────────────────────────────────────────────────
    # Roll-up endpoints powering the fleet overview tiles. The
    # janitor side owns the JSONB read so Django doesn't reach across DBs.

    def get_models(self) -> dict:
        """The served-model catalog + curated auto-level map. Project-agnostic
        (the gateway catalog is global), so no params."""
        return self._call("GET", "/models")

    def get_spec_schema(self, *, section: str | None = None) -> dict:
        """The agent-spec JSON Schema, emitted from the canonical zod
        `AgentSpecSchema` (no Python mirror). Optional `section` returns one
        top-level slice (e.g. `models`, `triggers`, `limits`)."""
        params: dict[str, Any] = {}
        if section:
            params["section"] = section
        return self._call("GET", "/spec-schema", params=params)

    def aggregate_for_application(self, application_id: str, *, since: str | None = None) -> dict:
        params: dict[str, Any] = {"application_id": application_id}
        if since:
            params["since"] = since
        return self._call("GET", "/sessions/stats", params=params)

    def aggregate_for_team(self, team_id: int, *, since: str | None = None) -> dict:
        params: dict[str, Any] = {"team_id": team_id}
        if since:
            params["since"] = since
        return self._call("GET", "/fleet/stats", params=params)

    def list_live_for_team(self, team_id: int, *, limit: int | None = None) -> dict:
        params: dict[str, Any] = {"team_id": team_id}
        if limit is not None:
            params["limit"] = limit
        return self._call("GET", "/sessions/live", params=params)

    def clone_from(self, target_revision_id: str, source_revision_id: str) -> dict:
        return self._call(
            "POST",
            f"/revisions/{target_revision_id}/clone_from",
            json={"source_revision_id": source_revision_id},
        )

    # ── approvals ──────────────────────────────────────────────────────────

    def list_approvals(
        self,
        application_id: str,
        *,
        state: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        params: dict[str, Any] = {"application_id": application_id}
        if state:
            params["state"] = state
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._call("GET", "/approvals", params=params)

    def list_approvals_for_team(
        self,
        team_id: int,
        *,
        application_id: str | None = None,
        state: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        params: dict[str, Any] = {"team_id": team_id}
        if application_id:
            params["application_id"] = application_id
        if state:
            params["state"] = state
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._call("GET", "/fleet/approvals", params=params)

    def get_approval(self, approval_id: str, *, application_id: str | None = None) -> dict:
        # application_id scopes the janitor's read to this tenant (defence in
        # depth alongside the app/team gate the view already enforces).
        params = {"application_id": application_id} if application_id else None
        return self._call("GET", f"/approvals/{approval_id}", params=params)

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        edited_args: dict[str, Any] | None = None,
        reason: str | None = None,
        application_id: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"decision": decision, "decided_by": decided_by}
        if edited_args is not None:
            body["edited_args"] = edited_args
        if reason is not None:
            body["reason"] = reason
        params = {"application_id": application_id} if application_id else None
        return self._call("POST", f"/approvals/{approval_id}/decide", json=body, params=params)

    # ── catalog ────────────────────────────────────────────────────────────

    def native_tools(self) -> dict:
        return self._call("GET", "/native_tools")

    # ── memory ─────────────────────────────────────────────────────────────
    # S3-backed memory files surface. Each agent has its own prefix; the
    # runner writes via the @posthog/memory-* tools, humans write via these
    # endpoints. Both share the same bucket — see
    # services/agent-shared/src/memory/store.ts for the key layout.

    def list_memory_files(self, team_id: int, application_id: str, *, prefix: str | None = None) -> dict:
        params: dict[str, Any] = {}
        if prefix:
            params["prefix"] = prefix
        return self._call(
            "GET",
            f"/memory/team/{team_id}/agent/{application_id}/files",
            params=params,
        )

    def get_memory_tree(self, team_id: int, application_id: str) -> dict:
        return self._call("GET", f"/memory/team/{team_id}/agent/{application_id}/tree")

    # Tabular reference (the @posthog/table-* tools' JSONL tables) — read-only,
    # surfaced in the console's memory tab alongside the markdown files.
    def list_tables(self, team_id: int, application_id: str) -> dict:
        return self._call("GET", f"/tables/team/{team_id}/agent/{application_id}")

    def read_table(self, team_id: int, application_id: str, name: str, *, limit: int | None = None) -> dict:
        params: dict[str, Any] = {}
        if limit:
            params["limit"] = limit
        return self._call("GET", f"/tables/team/{team_id}/agent/{application_id}/{name}", params=params)

    def read_memory_file(self, team_id: int, application_id: str, path: str) -> dict:
        # The janitor uses the URL tail (Express `:path(.*)`) for the file path,
        # so `incidents/db.md` becomes `/files/incidents/db.md`. We don't
        # url-encode the slashes — the slash IS the path separator, and the
        # janitor's `validateMemoryPath` rejects anything dodgy.
        return self._call(
            "GET",
            f"/memory/team/{team_id}/agent/{application_id}/files/{path.lstrip('/')}",
        )

    def write_memory_file(
        self,
        team_id: int,
        application_id: str,
        *,
        path: str,
        description: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"path": path, "description": description, "content": content}
        if tags is not None:
            body["tags"] = tags
        return self._call("POST", f"/memory/team/{team_id}/agent/{application_id}/files", json=body)

    def update_memory_file(
        self,
        team_id: int,
        application_id: str,
        path: str,
        *,
        description: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if description is not None:
            body["description"] = description
        if content is not None:
            body["content"] = content
        if tags is not None:
            body["tags"] = tags
        return self._call(
            "PATCH",
            f"/memory/team/{team_id}/agent/{application_id}/files/{path.lstrip('/')}",
            json=body,
        )

    def delete_memory_file(self, team_id: int, application_id: str, path: str) -> dict:
        return self._call(
            "DELETE",
            f"/memory/team/{team_id}/agent/{application_id}/files/{path.lstrip('/')}",
        )

    def search_memory(
        self,
        team_id: int,
        application_id: str,
        *,
        q: str,
        prefix: str | None = None,
        limit: int | None = None,
    ) -> dict:
        params: dict[str, Any] = {"q": q}
        if prefix:
            params["prefix"] = prefix
        if limit is not None:
            params["limit"] = limit
        return self._call("GET", f"/memory/team/{team_id}/agent/{application_id}/search", params=params)

    # ── users + linked identities ──────────────────────────────────────────
    # The agent's end-users (agent_user) and their linked connections
    # (agent_identity_credential). Metadata only — the janitor holds no
    # decryption key, so credential material never crosses this boundary.

    def list_users(self, team_id: int, application_id: str) -> dict:
        """List the agent's end-users, each with their linked connections."""
        return self._call("GET", f"/users/team/{team_id}/agent/{application_id}")

    def delete_connection(self, team_id: int, application_id: str, agent_user_id: str, provider: str) -> dict:
        """Revoke one linked connection (kept for audit, not hard-deleted)."""
        return self._call(
            "DELETE",
            f"/users/team/{team_id}/agent/{application_id}/user/{agent_user_id}/connections/{provider}",
        )


def default_client() -> JanitorClient:
    """One module-level singleton. Tests inject by monkey-patching this."""
    return _CLIENT


_CLIENT = JanitorClient()
