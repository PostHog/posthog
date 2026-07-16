"""
Integration tests: AgentApplicationViewSet runtime bridge actions
(`agent_invoke` / `agent_send` / `agent_listen`) ↔ the agent-ingress client.

These actions are the LIVE-agent runtime surface behind the `agent-applications-invoke` /
`agent-applications-send` / `agent-applications-listen` MCP tools. They talk to the ingress over
`_ingress()` (public run/send + internal digest RPC) and check session
ownership against the janitor via `_janitor().get_session`. Both boundaries are
mocked so no live ingress / janitor process is needed — the contract under test
is Django-side: the pre-flight guards (no live revision, cross-app session), the
caller-PAT forwarding, and the `_map_ingress_error` mapping that turns ingress
404 `no_chat_trigger` / terminal 410 / 403 `elevation_required` / 5xx into clean
responses instead of a bare 500. The runtime side (real PG, real session
creation) is exercised in the node harness (`services/agent-tests`) and
`services/agent-ingress/src/routing/*.test.ts`.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ..logic.ingress_client import IngressClientError
from ..logic.janitor_client import JanitorClientError
from ..models import AgentApplication, AgentRevision

_SESSION_ID = "33333333-3333-3333-3333-333333333333"


def _base_spec() -> dict:
    return {
        "model": "test/x",
        "triggers": [{"type": "chat", "config": {}, "auth": {"modes": [{"type": "posthog", "scopes": []}]}}],
    }


class TestAgentRuntimeBridge(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="runtime-agent",
            name="Runtime agent",
            description="",
        )
        self.base = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"

    def _make_live_revision(self) -> AgentRevision:
        rev = AgentRevision.all_teams.create(
            application=self.application,
            state="live",
            bundle_uri="fs://test/",
            spec=_base_spec(),
        )
        self.application.live_revision = rev
        self.application.save(update_fields=["live_revision"])
        return rev

    # ── agent_invoke ─────────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_without_live_revision_returns_400(self, mock_ingress: MagicMock) -> None:
        # No revision promoted → the action rejects before any ingress call.
        res = self.client.post(f"{self.base}/invoke/", {"message": "hi"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("no live revision", res.content.decode().lower())
        mock_ingress.return_value.run.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_happy_path_returns_session_state_resumed(self, mock_ingress: MagicMock) -> None:
        self._make_live_revision()
        mock_ingress.return_value.run.return_value = {"session_id": _SESSION_ID, "resumed": True}
        res = self.client.post(f"{self.base}/invoke/", {"message": "start it"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["session_id"], _SESSION_ID)
        self.assertEqual(body["state"], "queued")
        self.assertTrue(body["resumed"])  # external_key matched → resumed surfaced
        # Forwards message + slug (+ the Authorization kwarg) to the ingress run route.
        args, kwargs = mock_ingress.return_value.run.call_args
        self.assertEqual(kwargs["message"], "start it")
        self.assertEqual(args[0], self.application.slug)
        self.assertIn("authorization", kwargs)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_forwards_caller_pat_to_ingress(self, mock_ingress: MagicMock) -> None:
        # The central auth decision: the caller's PAT is forwarded verbatim so the
        # ingress `posthog` mode re-introspects it and the session principal is the
        # real caller. Authenticate with a real scoped PAT and assert it lands.
        self._make_live_revision()
        mock_ingress.return_value.run.return_value = {"session_id": _SESSION_ID}
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="runtime-test", user=self.user, secure_value=hash_key_value(raw), scopes=["agents:write"]
        )
        res = self.client.post(
            f"{self.base}/invoke/", {"message": "hi"}, format="json", HTTP_AUTHORIZATION=f"Bearer {raw}"
        )
        self.assertEqual(res.status_code, 200, res.content)
        _, kwargs = mock_ingress.return_value.run.call_args
        self.assertEqual(kwargs["authorization"], f"Bearer {raw}")

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_no_chat_trigger_maps_to_clean_400(self, mock_ingress: MagicMock) -> None:
        # A slack/cron-only agent 404s `no_chat_trigger` at the ingress; the view
        # must reframe that as a 400 (not a 404 "not found" and not a bare 500).
        self._make_live_revision()
        mock_ingress.return_value.run.side_effect = IngressClientError(
            404, "ingress returned 404", body={"error": "no_chat_trigger"}
        )
        res = self.client.post(f"{self.base}/invoke/", {"message": "hi"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("no chat trigger", res.content.decode().lower())

    # ── agent_send ───────────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_to_session_from_another_app_returns_404(
        self, mock_janitor: MagicMock, mock_ingress: MagicMock
    ) -> None:
        # The janitor row says this session belongs to a DIFFERENT application →
        # the ownership pre-flight raises NotFound before any ingress send.
        mock_janitor.return_value.get_session.return_value = {"application_id": "some-other-app-id"}
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 404, res.content)
        mock_ingress.return_value.send.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_to_terminal_session_passes_410_through(
        self, mock_janitor: MagicMock, mock_ingress: MagicMock
    ) -> None:
        # Ownership passes; the ingress reports the session is truly terminal (410).
        # The view preserves the 410 verbatim (preserve-4xx doctrine) with an
        # actionable message — never a bare 500, and no longer remapped to 400.
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.side_effect = IngressClientError(
            410, "ingress returned 410", body={"state": "closed"}
        )
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 410, res.content)
        self.assertIn("terminal", res.content.decode().lower())
        # A 410 is an EXPECTED client condition, so it must render a clean client-error
        # type/code (SessionGoneError), NOT the bare-APIException `server_error`/`error`
        # that would page on-call and pollute error monitoring.
        body = res.json()
        self.assertEqual(body["type"], "invalid_request", res.content)
        self.assertEqual(body["code"], "session_gone", res.content)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_elevation_required_preserves_request_id(
        self, mock_janitor: MagicMock, mock_ingress: MagicMock
    ) -> None:
        # A non-owner send is denied 403 `elevation_required`; the view must surface
        # the actionable elevation_request_id, not collapse to the opaque code.
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.side_effect = IngressClientError(
            403,
            "ingress returned 403",
            body={"error": "elevation_required", "elevation_request_id": "elev-123", "session_id": _SESSION_ID},
        )
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 403, res.content)
        self.assertIn("elev-123", res.content.decode())
        # A non-owner 403 is an EXPECTED client condition (the caller must run the
        # elevation flow), so it renders a clean auth-error type + the actionable
        # `elevation_required` code (ElevationRequiredError), NOT `server_error`/`error`.
        body = res.json()
        self.assertEqual(body["type"], "authentication_error", res.content)
        self.assertEqual(body["code"], "elevation_required", res.content)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_ingress_5xx_clamps_to_502(self, mock_janitor: MagicMock, mock_ingress: MagicMock) -> None:
        # An ingress 5xx must not leak as a 4xx or a bare 500 — it clamps to 502.
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.side_effect = IngressClientError(503, "ingress returned 503", body=None)
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 502, res.content)
        # A clamped 5xx IS genuinely a server-side failure, so it correctly keeps the
        # `server_error` type (IngressUpstreamError leaves the default) under the
        # `ingress_upstream` code — the 4xx path is what must NOT read as server_error.
        body = res.json()
        self.assertEqual(body["type"], "server_error", res.content)
        self.assertEqual(body["code"], "ingress_upstream", res.content)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_happy_path_returns_state(self, mock_janitor: MagicMock, mock_ingress: MagicMock) -> None:
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.return_value = {}
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {"state": "queued"})
        _, kwargs = mock_ingress.return_value.send.call_args
        self.assertEqual(kwargs["session_id"], _SESSION_ID)
        self.assertEqual(kwargs["message"], "more")
        self.assertIn("authorization", kwargs)

    # ── agent_listen ─────────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_listen_happy_path_passes_through_digest(self, mock_ingress: MagicMock) -> None:
        # listen does NOT pre-check the janitor (see the action comment) — tenancy is
        # enforced by the ingress digest's application_id re-scope, so only _ingress
        # is on the path.
        digest = {
            "session_id": _SESSION_ID,
            "state": "running",
            "turns": 2,
            "next_cursor": 2,
            "digest": "working…\n\nTools: (none)",
            "truncated": False,
            "done": False,
        }
        mock_ingress.return_value.session_digest.return_value = digest
        res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), digest)
        _, kwargs = mock_ingress.return_value.session_digest.call_args
        self.assertEqual(kwargs["application_id"], str(self.application.id))
        self.assertEqual(kwargs["session_id"], _SESSION_ID)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_listen_from_another_app_returns_404(self, mock_ingress: MagicMock) -> None:
        # Cross-tenant listen still 404s end-to-end: the ingress digest re-scopes by
        # the team-checked application_id and returns session_not_found for a foreign
        # session, which _map_ingress_error turns into a 404 — the tenancy guarantee
        # the removed janitor pre-check used to give, now enforced at the ingress read.
        mock_ingress.return_value.session_digest.side_effect = IngressClientError(
            404, "ingress returned 404", body={"error": "session_not_found"}
        )
        res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}")
        self.assertEqual(res.status_code, 404, res.content)

    def test_listen_without_session_id_returns_400(self) -> None:
        res = self.client.get(f"{self.base}/listen/")
        self.assertEqual(res.status_code, 400, res.content)

    def test_listen_non_uuid_session_id_returns_400(self) -> None:
        # A malformed session_id must be a clean 400, not a 502 from a Postgres
        # "invalid input syntax for type uuid" bubbling up through the janitor.
        res = self.client.get(f"{self.base}/listen/?session_id=not-a-uuid")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("uuid", res.content.decode().lower())

    # ── error mapping + input validation ─────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_plain_404_maps_to_propagating_message(self, mock_ingress: MagicMock) -> None:
        # A plain 404 from the ingress (not `no_chat_trigger`) → invoke's own
        # not_found_detail, phrased as "still propagating" (the agent has no
        # session context of its own), never a bare 404 "Session not found".
        self._make_live_revision()
        mock_ingress.return_value.run.side_effect = IngressClientError(
            404, "ingress returned 404", body={"error": "session_not_found"}
        )
        res = self.client.post(f"{self.base}/invoke/", {"message": "hi"}, format="json")
        self.assertEqual(res.status_code, 404, res.content)
        self.assertIn("propagating", res.content.decode().lower())

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_invoke_blank_message_returns_400(self, mock_ingress: MagicMock) -> None:
        self._make_live_revision()
        res = self.client.post(f"{self.base}/invoke/", {"message": ""}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        mock_ingress.return_value.run.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_send_blank_message_returns_400(self, mock_ingress: MagicMock) -> None:
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": ""}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        mock_ingress.return_value.send.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._ingress")
    def test_send_non_uuid_session_id_returns_400(self, mock_ingress: MagicMock) -> None:
        # The serializer's UUIDField rejects a malformed session_id up front.
        res = self.client.post(f"{self.base}/send/", {"session_id": "not-a-uuid", "message": "hi"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        mock_ingress.return_value.send.assert_not_called()

    def test_listen_negative_cursor_returns_400(self) -> None:
        res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}&cursor=-1")
        self.assertEqual(res.status_code, 400, res.content)

    def test_listen_non_integer_cursor_returns_400(self) -> None:
        res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}&cursor=abc")
        self.assertEqual(res.status_code, 400, res.content)

    def test_listen_non_integer_max_chars_returns_400(self) -> None:
        res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}&max_chars=abc")
        self.assertEqual(res.status_code, 400, res.content)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_janitor_failure_maps_to_502(self, mock_janitor: MagicMock, mock_ingress: MagicMock) -> None:
        # send's ownership pre-flight talks to the janitor; a janitor 5xx must clamp
        # to a clean 502, never bubble as a bare 500 or reach the ingress. (listen
        # has no janitor pre-check, so this guard lives on send.)
        mock_janitor.return_value.get_session.side_effect = JanitorClientError(503, "janitor down", body=None)
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "hi"}, format="json")
        self.assertEqual(res.status_code, 502, res.content)
        mock_ingress.return_value.send.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_janitor_404_normalizes_to_clean_not_found(
        self, mock_janitor: MagicMock, mock_ingress: MagicMock
    ) -> None:
        # A janitor 404 for a never-existed session is a not-found for the caller —
        # it must surface as a clean 404 `not_found` (invalid_request), NOT leak the
        # internal `janitor_upstream` label, matching the sibling clean paths.
        mock_janitor.return_value.get_session.side_effect = JanitorClientError(404, "no such session", body=None)
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "hi"}, format="json")
        self.assertEqual(res.status_code, 404, res.content)
        self.assertEqual(res.json().get("code"), "not_found", res.content)
        self.assertNotIn("janitor_upstream", res.content.decode())
        mock_ingress.return_value.send.assert_not_called()

    def test_listen_max_chars_out_of_range_returns_400(self) -> None:
        # max_chars must be in [1, 20000] (symmetric with cursor >= 0 and the ingress
        # zod ceiling) so a 0 / negative / oversized value is a clean field-level 400,
        # not the opaque ingress `invalid_body`.
        for bad in ("0", "-5", "20001"):
            res = self.client.get(f"{self.base}/listen/?session_id={_SESSION_ID}&max_chars={bad}")
            self.assertEqual(res.status_code, 400, f"max_chars={bad}: {res.content!r}")
            self.assertIn("max_chars", res.content.decode())

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_non_elevation_403_preserves_status(self, mock_janitor: MagicMock, mock_ingress: MagicMock) -> None:
        # A 403 that is NOT `elevation_required` falls through to IngressUpstreamError,
        # which preserves the upstream 4xx status verbatim.
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.side_effect = IngressClientError(
            403, "ingress returned 403", body={"error": "forbidden"}
        )
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 403, res.content)
        # A preserved (non-elevation) 4xx flows through IngressUpstreamError, which must
        # label it a client error (`invalid_request`), not the bare `server_error`.
        body = res.json()
        self.assertEqual(body["type"], "invalid_request", res.content)
        self.assertEqual(body["code"], "ingress_upstream", res.content)

    @patch("products.agent_platform.backend.presentation.views._ingress")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_send_unmapped_4xx_preserves_status(self, mock_janitor: MagicMock, mock_ingress: MagicMock) -> None:
        # An unmapped 422 preserves the upstream status through IngressUpstreamError.
        mock_janitor.return_value.get_session.return_value = {"application_id": str(self.application.id)}
        mock_ingress.return_value.send.side_effect = IngressClientError(
            422, "ingress returned 422", body={"error": "unprocessable"}
        )
        res = self.client.post(f"{self.base}/send/", {"session_id": _SESSION_ID, "message": "more"}, format="json")
        self.assertEqual(res.status_code, 422, res.content)
        # Same class as the 403 passthrough: a preserved upstream 4xx must render as a
        # client error, never `server_error`.
        body = res.json()
        self.assertEqual(body["type"], "invalid_request", res.content)
        self.assertEqual(body["code"], "ingress_upstream", res.content)
