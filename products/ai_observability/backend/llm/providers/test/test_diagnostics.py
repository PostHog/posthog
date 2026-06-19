import pytest

import httpx
import openai
import anthropic
import posthoganalytics

from products.ai_observability.backend.llm.providers._diagnostics import _tag_response, tagged_http_client


def _make_response(status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.com"),
    )


class TestTagResponse:
    def test_tags_status_and_x_request_id(self):
        with posthoganalytics.new_context():
            _tag_response(_make_response(200, {"x-request-id": "req_abc"}))
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 200
            assert tags["provider.last_request_id"] == "req_abc"

    def test_falls_back_to_anthropic_request_id_header(self):
        with posthoganalytics.new_context():
            _tag_response(_make_response(429, {"anthropic-request-id": "req_ant"}))
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 429
            assert tags["provider.last_request_id"] == "req_ant"

    def test_falls_back_to_openai_request_id_header(self):
        with posthoganalytics.new_context():
            _tag_response(_make_response(403, {"openai-request-id": "req_oai"}))
            assert posthoganalytics.get_tags()["provider.last_request_id"] == "req_oai"

    def test_status_tagged_even_when_request_id_missing(self):
        with posthoganalytics.new_context():
            _tag_response(_make_response(500))
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 500
            assert "provider.last_request_id" not in tags

    def test_does_not_raise_when_called_outside_any_context(self):
        # The Temporal-side activity wrappers create the context; if a hook
        # somehow fires before that scope is open, we must not crash the request.
        _tag_response(_make_response(200, {"x-request-id": "req_outside"}))

    def test_does_not_leak_tags_outside_the_context(self):
        # Belt-and-braces: contextvar isolation should already give us this, but
        # this test pins the invariant so a future change to the helper that
        # accidentally writes to global state fails loudly.
        with posthoganalytics.new_context():
            _tag_response(_make_response(200, {"x-request-id": "req_inside"}))
        assert "provider.last_status" not in posthoganalytics.get_tags()
        assert "provider.last_request_id" not in posthoganalytics.get_tags()


class TestSDKIntegration:
    """Verify the hook fires when the SDK actually drives the http_client.

    Guards against future regressions where `http_client=` is dropped or routed
    to a constructor that ignores it — the unit tests above would still pass.
    """

    @staticmethod
    def _swap_mock_transport(client: httpx.Client, handler) -> None:
        client._transport = httpx.MockTransport(handler)

    def test_openai_sdk_invokes_hook(self):
        http_client = tagged_http_client()
        self._swap_mock_transport(
            http_client,
            lambda req: httpx.Response(
                200,
                headers={"x-request-id": "req_openai_test"},
                json={
                    "id": "chatcmpl-x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "gpt-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "hi"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ),
        )
        client = openai.OpenAI(api_key="sk-test", http_client=http_client)

        with posthoganalytics.new_context():
            client.chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 200
            assert tags["provider.last_request_id"] == "req_openai_test"

    def test_anthropic_sdk_invokes_hook(self):
        http_client = tagged_http_client()
        self._swap_mock_transport(
            http_client,
            lambda req: httpx.Response(
                200,
                headers={"anthropic-request-id": "req_anthropic_test"},
                json={
                    "id": "msg_x",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "model": "claude-test",
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            ),
        )
        client = anthropic.Anthropic(api_key="sk-test", http_client=http_client)

        with posthoganalytics.new_context():
            client.messages.create(
                model="claude-test",
                max_tokens=4,
                messages=[{"role": "user", "content": "hi"}],
            )
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 200
            assert tags["provider.last_request_id"] == "req_anthropic_test"

    def test_hook_does_not_break_request_on_provider_error(self):
        # 4xx/5xx responses should still tag and not interfere with the SDK's
        # own exception-raising path.
        http_client = tagged_http_client()
        self._swap_mock_transport(
            http_client,
            lambda req: httpx.Response(
                403,
                headers={"x-request-id": "req_perm_denied"},
                json={"error": {"code": "model_not_found", "message": "no access", "type": "invalid_request_error"}},
            ),
        )
        client = openai.OpenAI(api_key="sk-test", http_client=http_client)

        with posthoganalytics.new_context():
            with pytest.raises(openai.PermissionDeniedError):
                client.chat.completions.create(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
            tags = posthoganalytics.get_tags()
            assert tags["provider.last_status"] == 403
            assert tags["provider.last_request_id"] == "req_perm_denied"
