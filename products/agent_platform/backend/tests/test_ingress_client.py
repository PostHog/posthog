"""
Unit tests for the agent-ingress HTTP client (logic/ingress_client.py) — the thin
transport behind the `agent-applications-invoke` / `agent-applications-send` / `agent-applications-listen` MCP tools. The
viewset bridge is covered in test_agent_runtime_bridge.py against a mocked client;
here we test the client itself in isolation by stubbing the outbound
`internal_requests.request`, so no live ingress process is needed. Focus: the
`_call` error/empty-body mapping, header assembly, and the internal-JWT
fail-open branch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests

from ..logic.ingress_client import IngressClient, IngressClientError

_INGRESS = "products.agent_platform.backend.logic.ingress_client.internal_requests"

_SIGNING_KEY = "test-internal-signing-key"


def _resp(status_code: int, *, json_body=None, content: bytes = b"{}", raises_value_error: bool = False) -> MagicMock:
    """Fake requests.Response — only the attributes `_call` touches."""
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    if raises_value_error:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = json_body
    return r


class TestIngressClientCall(SimpleTestCase):
    def setUp(self) -> None:
        self.client = IngressClient(base_url="http://ingress.test")

    @patch(_INGRESS)
    def test_call_raises_with_body_on_4xx_5xx(self, mock_ingress: MagicMock) -> None:
        # A 503 with a JSON error body → IngressClientError carrying status + body.
        mock_ingress.request.return_value = _resp(503, json_body={"error": "unavailable"}, content=b'{"error":"x"}')
        with self.assertRaises(IngressClientError) as ctx:
            self.client._call("POST", "/x", headers={})
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.body, {"error": "unavailable"})

    @patch(_INGRESS)
    def test_call_maps_transport_failure_to_502(self, mock_ingress: MagicMock) -> None:
        # A network-level RequestException must clamp to a clean 502, never leak raw.
        mock_ingress.request.side_effect = requests.RequestException("connection refused")
        with self.assertRaises(IngressClientError) as ctx:
            self.client._call("POST", "/x", headers={})
        self.assertEqual(ctx.exception.status_code, 502)

    @patch(_INGRESS)
    def test_call_returns_empty_dict_for_empty_content(self, mock_ingress: MagicMock) -> None:
        # A 200 with no body (e.g. send's ack) → {} rather than a JSON parse attempt.
        resp = _resp(200, content=b"")
        mock_ingress.request.return_value = resp
        self.assertEqual(self.client._call("POST", "/x", headers={}), {})
        resp.json.assert_not_called()

    @patch(_INGRESS)
    def test_call_error_body_none_when_not_json(self, mock_ingress: MagicMock) -> None:
        # A non-JSON error body (e.g. an HTML 502 page) → body=None, not a crash.
        mock_ingress.request.return_value = _resp(500, content=b"<html>oops</html>", raises_value_error=True)
        with self.assertRaises(IngressClientError) as ctx:
            self.client._call("GET", "/x", headers={})
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIsNone(ctx.exception.body)

    @patch(_INGRESS)
    def test_call_returns_parsed_json_on_2xx(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={"session_id": "s1"}, content=b'{"session_id":"s1"}')
        self.assertEqual(self.client._call("POST", "/x", headers={}), {"session_id": "s1"})


class TestIngressClientHeaders(SimpleTestCase):
    def test_forward_headers_includes_authorization_when_present(self) -> None:
        h = IngressClient._forward_headers("Bearer x")
        self.assertEqual(h["authorization"], "Bearer x")
        self.assertEqual(h["content-type"], "application/json")

    def test_forward_headers_omits_authorization_when_none(self) -> None:
        h = IngressClient._forward_headers(None)
        self.assertNotIn("authorization", h)

    @override_settings(AGENT_INTERNAL_SIGNING_KEY=_SIGNING_KEY)
    def test_internal_headers_signs_when_key_configured(self) -> None:
        h = IngressClient._internal_headers()
        self.assertIn("x-internal-secret", h)
        self.assertTrue(h["x-internal-secret"])

    @override_settings(AGENT_INTERNAL_SIGNING_KEY=None)
    def test_internal_headers_fail_open_when_no_key(self) -> None:
        # Dev / harness path: no shared key → no secret header (ingress gate is
        # also bypassed there), never a crash.
        h = IngressClient._internal_headers()
        self.assertNotIn("x-internal-secret", h)


class TestIngressClientRoutes(SimpleTestCase):
    def setUp(self) -> None:
        self.client = IngressClient(base_url="http://ingress.test")

    @patch(_INGRESS)
    def test_run_assembles_method_path_and_omits_external_key_when_none(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={"session_id": "s1"}, content=b"{}")
        self.client.run("my-agent", message="hi", external_key=None, authorization="Bearer x")
        args, kwargs = mock_ingress.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "http://ingress.test/agents/my-agent/run")
        self.assertEqual(kwargs["json"], {"message": "hi"})
        self.assertEqual(kwargs["headers"]["authorization"], "Bearer x")

    @patch(_INGRESS)
    def test_run_includes_external_key_when_present(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={}, content=b"{}")
        self.client.run("my-agent", message="hi", external_key="thread-9", authorization=None)
        _, kwargs = mock_ingress.request.call_args
        self.assertEqual(kwargs["json"], {"message": "hi", "external_key": "thread-9"})

    @patch(_INGRESS)
    def test_send_assembles_body(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={}, content=b"{}")
        self.client.send("my-agent", session_id="s1", message="more", authorization="Bearer x")
        args, kwargs = mock_ingress.request.call_args
        self.assertEqual(args[1], "http://ingress.test/agents/my-agent/send")
        self.assertEqual(kwargs["json"], {"session_id": "s1", "message": "more"})

    @override_settings(AGENT_INTERNAL_SIGNING_KEY=_SIGNING_KEY)
    @patch(_INGRESS)
    def test_session_digest_omits_cursor_and_max_chars_when_none(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={"digest": "x"}, content=b"{}")
        self.client.session_digest(application_id="app-1", session_id="s1", cursor=None, max_chars=None)
        args, kwargs = mock_ingress.request.call_args
        self.assertEqual(args[1], "http://ingress.test/internal/session-digest")
        self.assertEqual(kwargs["json"], {"application_id": "app-1", "session_id": "s1"})
        self.assertIn("x-internal-secret", kwargs["headers"])

    @override_settings(AGENT_INTERNAL_SIGNING_KEY=_SIGNING_KEY)
    @patch(_INGRESS)
    def test_session_digest_includes_cursor_and_max_chars_when_set(self, mock_ingress: MagicMock) -> None:
        mock_ingress.request.return_value = _resp(200, json_body={"digest": "x"}, content=b"{}")
        self.client.session_digest(application_id="app-1", session_id="s1", cursor=2, max_chars=500)
        _, kwargs = mock_ingress.request.call_args
        self.assertEqual(kwargs["json"], {"application_id": "app-1", "session_id": "s1", "cursor": 2, "max_chars": 500})
