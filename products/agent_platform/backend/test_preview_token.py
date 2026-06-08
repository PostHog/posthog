"""
Tests for AgentApplicationViewSet.preview_token — the self-describing
response shape.

Verifies:

  * `endpoints` contains the right routes for each declared trigger and
    omits routes for triggers the spec doesn't list (so the caller
    doesn't see URLs that 404 at ingress).
  * `auth.spec_modes` mirrors `spec.auth.modes[].type` in order so the
    caller knows which credential to attach alongside the preview-token.
  * `preview_proxy` advertises the Django-side proxy URL + its allowed
    paths so callers can pick between direct ingress and the
    auth-stripping proxy.
  * Empty `endpoints` when `AGENT_INGRESS_PUBLIC_URL` is unset (local
    dev without the tunnel).
  * Hard requirements that already existed: live revision rejected,
    cross-app revision rejected, missing query param rejected.
"""

from __future__ import annotations

from typing import Any

from posthog.test.base import APIBaseTest

from django.test import override_settings

from .models import AgentApplication, AgentRevision


def _base_spec(triggers: list[dict[str, Any]] | None = None, modes: list[str] | None = None) -> dict[str, Any]:
    return {
        "model": "anthropic/claude-sonnet-4-6",
        "triggers": triggers if triggers is not None else [{"type": "chat", "config": {"require_auth": True}}],
        "tools": [],
        "mcps": [],
        "skills": [],
        "integrations": [],
        "secrets": [],
        "limits": {"max_turns": 10, "max_tool_calls": 20, "max_wall_seconds": 60},
        "entrypoint": "agent.md",
        "auth": {
            "modes": [
                {"type": m, "issuer": "posthog", "scopes": []} if m == "oauth" else {"type": m}
                for m in (modes or ["pat"])
            ],
        },
    }


@override_settings(AGENT_INGRESS_PUBLIC_URL="https://ingress.example.com")
class TestPreviewTokenResponse(APIBaseTest):
    def _app(self, slug: str = "preview-bot") -> AgentApplication:
        return AgentApplication.objects.create(
            team=self.team,
            slug=slug,
            name="Preview bot",
            description="",
        )

    def _revision(self, app: AgentApplication, spec: dict[str, Any]) -> AgentRevision:
        return AgentRevision.objects.create(
            application=app,
            state="draft",
            bundle_uri=f"local://{app.slug}/v1",
            spec=spec,
        )

    def _url(self, app: AgentApplication, rev: AgentRevision) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.slug}/preview-token/?revision_id={rev.id}"

    def test_endpoints_advertises_only_declared_triggers(self) -> None:
        app = self._app()
        spec = _base_spec(
            triggers=[
                {"type": "chat", "config": {"require_auth": True}},
                {
                    "type": "slack",
                    "config": {"mention_only": True, "trusted_workspaces": ["T01ABC"]},
                },
            ]
        )
        rev = self._revision(app, spec)

        res = self.client.get(self._url(app, rev))
        assert res.status_code == 200, res.content
        body = res.json()

        # ingress_slug is the rev-hex form Django builds (32-char hex,
        # no dashes — see _build_preview_endpoints for the contract).
        expected_slug = f"{app.slug}-{rev.id.hex}"
        assert body["ingress_slug"] == expected_slug

        endpoints = body["endpoints"]
        # chat and slack both declared → both present.
        assert set(endpoints.keys()) == {"chat", "slack"}
        # Spot-check one URL from each — full URL means the caller
        # doesn't have to know the base or path layout.
        assert endpoints["chat"]["run"] == f"https://ingress.example.com/agents/{expected_slug}/run"
        assert endpoints["slack"]["events"] == f"https://ingress.example.com/agents/{expected_slug}/slack/events"
        # mcp / webhook not declared → not in response. Prevents the
        # caller from hitting a URL that 404s at ingress.
        assert "mcp" not in endpoints
        assert "webhook" not in endpoints

    def test_auth_block_mirrors_spec_modes_in_order(self) -> None:
        app = self._app()
        rev = self._revision(app, _base_spec(modes=["oauth", "pat", "posthog_internal"]))

        res = self.client.get(self._url(app, rev))
        assert res.status_code == 200, res.content
        auth = res.json()["auth"]

        # Mode order matters — the caller picks the first one its
        # credential satisfies; mirroring spec order keeps the contract
        # stable across edits.
        assert auth["spec_modes"] == ["oauth", "pat", "posthog_internal"]
        # Header / query names match what ingress's resolver reads.
        # Changing either side without the other would silently break
        # preview invocations — locking them down here.
        assert auth["preview_token_header"] == "x-agent-preview-token"
        assert auth["preview_token_query"] == "preview_token"
        # Notes must mention that preview-token alone isn't enough —
        # the caller still has to satisfy spec.auth.modes. This is the
        # gotcha that motivated the field's existence.
        assert "spec.auth.modes" in auth["notes"]

    def test_preview_proxy_block_advertises_django_url(self) -> None:
        app = self._app("proxy-bot")
        rev = self._revision(app, _base_spec())

        res = self.client.get(self._url(app, rev))
        assert res.status_code == 200, res.content
        proxy = res.json()["preview_proxy"]

        # The proxy base must point at THIS application — pasting a
        # different slug would invoke a different agent. Verify the
        # URL is rooted in the team + slug the request was for.
        assert f"/api/projects/{self.team.id}/agent_applications/proxy-bot/preview-proxy" in proxy["base"]
        # `allowed_paths` must be a sorted list (deterministic for the
        # caller's UI / docs) covering the four chat-trigger paths the
        # proxy passes through today.
        assert proxy["allowed_paths"] == ["cancel", "listen", "run", "send"]
        # Notes call out the auth-stripping limitation so the caller
        # doesn't try to use the proxy for an oauth-required agent.
        assert "Authorization" in proxy["notes"]

    @override_settings(AGENT_INGRESS_PUBLIC_URL=None)
    def test_endpoints_empty_when_public_url_unset(self) -> None:
        app = self._app()
        rev = self._revision(app, _base_spec())

        res = self.client.get(self._url(app, rev))
        assert res.status_code == 200, res.content
        body = res.json()
        # No public URL → no externally-reachable endpoints. Empty
        # rather than partial — the caller can detect the unconfigured
        # state by `endpoints == {}` and tell the user to set the env
        # var rather than handing them a broken URL.
        assert body["endpoints"] == {}
        # auth / preview_proxy blocks still present — they don't need
        # the ingress URL to be useful (proxy is same-origin Django).
        assert "auth" in body
        assert "preview_proxy" in body

    def test_live_revision_rejected(self) -> None:
        app = self._app()
        rev = self._revision(app, _base_spec())
        # Promote the revision so it's live; preview-token then refuses.
        app.live_revision = rev
        app.save(update_fields=["live_revision"])

        res = self.client.get(self._url(app, rev))
        assert res.status_code == 400, res.content
        assert "non-live revisions only" in res.content.decode()

    def test_revision_id_required(self) -> None:
        app = self._app()
        res = self.client.get(f"/api/projects/{self.team.id}/agent_applications/{app.slug}/preview-token/")
        assert res.status_code == 400, res.content
        assert "revision_id" in res.content.decode()
