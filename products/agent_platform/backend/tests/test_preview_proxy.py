"""
Regression: AgentApplicationViewSet.preview_proxy — scope + renderer hygiene.

Locks down the two classes of bug we shipped landing the draft-preview
playground flow:

  * 403 `This action does not support personal API key access` —
    happened because the GET variant maps to a separate `view.action`
    name (`preview_proxy_get`) and we only had the POST one
    (`preview_proxy`) listed in `scope_object_read_actions`. Both names
    must be declared or OAuth/PAT callers get bounced.

  * 406 `Could not satisfy the request Accept header` — happened
    because browser `EventSource` sends `Accept: text/event-stream` and
    DRF's default renderer set doesn't claim that media type, so the
    request 406s before reaching the streaming view. The action's
    `renderer_classes` must include `EventStreamRenderer`.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from ..presentation.views import AgentApplicationViewSet, EventStreamRenderer


class TestPreviewProxyScope(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    @parameterized.expand(
        [
            # POST verbs (run / send / cancel) route through `preview_proxy`.
            ("preview_proxy",),
            # GET (SSE listen) routes through `preview_proxy_get` —
            # `view.action` resolves to the bound function name on the
            # `@preview_proxy.mapping.get` handler.
            ("preview_proxy_get",),
        ]
    )
    def test_action_is_a_declared_read_action(self, action_name: str) -> None:
        self.assertIn(action_name, AgentApplicationViewSet.scope_object_read_actions)


class TestPreviewProxyRendering(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
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
