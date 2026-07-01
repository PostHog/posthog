"""
Regression: AgentApplicationViewSet.preview_proxy — scope + renderer hygiene.

Locks down the two classes of bug we shipped landing the draft-preview
playground flow:

  * 403 `This action does not support personal API key access` —
    happened because the GET variant maps to a separate `view.action`
    name (`preview_proxy_get`) and we only had the POST one
    (`preview_proxy`) declared. Both names must appear in a scope list
    or OAuth/PAT callers get bounced. The two now sit in *different*
    lists: POST `preview_proxy` (run/send/cancel) is a mutating invoke
    → `:write`; the GET `listen` tail is read-only → `:read`.

  * 406 `Could not satisfy the request Accept header` — happened
    because browser `EventSource` sends `Accept: text/event-stream` and
    DRF's default renderer set doesn't claim that media type, so the
    request 406s before reaching the streaming view. The action's
    `renderer_classes` must include `EventStreamRenderer`.
"""

from __future__ import annotations

from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from ..models import AgentApplication, AgentRevision
from ..presentation.serializers import PreviewProxyInvokeRequestSerializer
from ..presentation.views import AgentApplicationViewSet, EventStreamRenderer


def _base_spec() -> dict[str, Any]:
    return {
        "model": "anthropic/claude-sonnet-4-6",
        "triggers": [{"type": "chat", "config": {}, "auth": {"modes": [{"type": "posthog", "scopes": []}]}}],
        "tools": [],
        "mcps": [],
        "skills": [],
        "secrets": [],
        "limits": {"max_turns": 10, "max_tool_calls": 20, "max_wall_seconds": 60},
    }


class TestPreviewProxyScope(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    @parameterized.expand(
        [
            # POST verbs (run / send / cancel) route through `preview_proxy` —
            # mutating invokes, so they require `:write`.
            ("preview_proxy", "scope_object_write_actions"),
            # GET (SSE listen) routes through `preview_proxy_get` —
            # `view.action` resolves to the bound function name on the
            # `@preview_proxy.mapping.get` handler. Read-only tail → `:read`.
            ("preview_proxy_get", "scope_object_read_actions"),
        ]
    )
    def test_action_is_declared_in_expected_scope_list(self, action_name: str, scope_list: str) -> None:
        self.assertIn(action_name, getattr(AgentApplicationViewSet, scope_list))


class TestPreviewProxyRendering(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def test_event_stream_renderer_claims_text_event_stream(self) -> None:
        # The renderer doesn't render — it only needs to win DRF's
        # content negotiation when `Accept: text/event-stream` arrives.
        self.assertEqual(EventStreamRenderer.media_type, "text/event-stream")

    def test_preview_proxy_renderers_include_event_stream(self) -> None:
        # The renderer set is attached to the `@action` (POST handler);
        # the GET via `@preview_proxy.mapping.get` inherits the same set
        # (`mapping.get` doesn't take its own kwargs).
        # DRF stashes action kwargs on `.kwargs` not on direct attributes.
        action_kwargs = getattr(AgentApplicationViewSet.preview_proxy, "kwargs", {})
        renderer_classes = action_kwargs.get("renderer_classes")
        self.assertIsNotNone(renderer_classes, "preview_proxy action should declare renderer_classes")
        assert renderer_classes is not None  # type narrowing for mypy
        self.assertIn(EventStreamRenderer, renderer_classes)


class TestPreviewProxyInvokeBody(APIBaseTest):
    """#4 — the proxy forwards the POST body to ingress (`run`/`send` carry
    `message`), but the action shipped `request=None`, so drf-spectacular
    published an empty body and the generated MCP tool had no way to pass a
    message. The action now declares `PreviewProxyInvokeRequestSerializer`;
    this pins the body shape it documents. (The OpenAPI wiring itself is
    verified by `hogli build:openapi`.)"""

    def test_invoke_serializer_documents_message_and_session_id(self) -> None:
        fields = PreviewProxyInvokeRequestSerializer().fields
        self.assertLessEqual({"message", "session_id"}, set(fields))
        # Optional: `run` needs only `message`; `cancel`/`listen` need neither.
        self.assertFalse(fields["message"].required)
        self.assertFalse(fields["session_id"].required)

    def test_invoke_serializer_validates_run_and_send_bodies(self) -> None:
        self.assertTrue(PreviewProxyInvokeRequestSerializer(data={"message": "tell me a joke"}).is_valid())
        self.assertTrue(
            PreviewProxyInvokeRequestSerializer(data={"session_id": "s-1", "message": "another"}).is_valid()
        )


class TestPreviewProxyCrossAppRejection(APIBaseTest):
    """Tenant boundary: minting via preview-proxy must not let a revision_id
    from one app smuggle through under a sibling app's slug. Same contract as
    `preview-token`, enforced via the same `application=application` filter."""

    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def _app(self, slug: str) -> AgentApplication:
        return AgentApplication.all_teams.create(team_id=self.team.id, slug=slug, name=slug, description="")

    def _revision(self, app: AgentApplication) -> AgentRevision:
        return AgentRevision.all_teams.create(
            application=app, state="draft", bundle_uri=f"local://{app.slug}/v1", spec=_base_spec()
        )

    def test_revision_from_different_app_in_same_team_rejected(self) -> None:
        app_a = self._app("preview-proxy-bot-a")
        app_b = self._app("preview-proxy-bot-b")
        rev_b = self._revision(app_b)
        # Hit POST /run (the canonical mutating invoke). The view rejects
        # before any upstream call, so no ingress is required.
        res = self.client.post(
            f"/api/projects/{self.team.id}/agent_applications/{app_a.slug}/preview-proxy/run/?revision_id={rev_b.id}",
            data={"message": "hi"},
            format="json",
        )
        assert res.status_code == 404, res.content
        assert "Revision not found in this application" in res.content.decode()
