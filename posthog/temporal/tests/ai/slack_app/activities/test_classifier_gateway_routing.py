"""Routing pin for the Slack classifiers: Go ai-gateway when its env pair is set, else the Python route."""

import json

from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.temporal.ai.slack_app.activities.classifiers import (
    classify_message_is_agent_directed,
    classify_slack_app_model_override,
    classify_task_needs_repo,
)

from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.backend.services.slack_messages import SlackThreadMessage

AI_GATEWAY_URL = "https://ai-gateway.example/v1"
AI_GATEWAY_KEY = "phs_go"
LLM_GATEWAY_URL = "http://llm-gateway:8080"
LLM_GATEWAY_KEY = "phx_legacy"

# Every setting the builders read is pinned in both modes, so a fallback to the other route
# cannot pass by accident.
GO_GATEWAY = {
    "AI_GATEWAY_URL": AI_GATEWAY_URL,
    "AI_GATEWAY_API_KEY": AI_GATEWAY_KEY,
    "LLM_GATEWAY_URL": LLM_GATEWAY_URL,
    "LLM_GATEWAY_API_KEY": LLM_GATEWAY_KEY,
}
PYTHON_GATEWAY = {**GO_GATEWAY, "AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": ""}

CHOICES = (ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),)
NEEDS_REPO_TEXT = "ambiguous ask the heuristic does not catch"


def _classify_needs_repo():
    return classify_task_needs_repo(NEEDS_REPO_TEXT, [SlackThreadMessage(user="Alessandro", text=NEEDS_REPO_TEXT)])


def _classify_agent_directed():
    return classify_message_is_agent_directed("also check the mobile breakpoint", "Fix checkout", [])


def _classify_model_override():
    return classify_slack_app_model_override("use fable for this", CHOICES)


OPENAI_CLASSIFIERS = [
    ("agent_directed", _classify_agent_directed, '{"agent_directed": true}'),
    ("model_override", _classify_model_override, '{"model": "claude-fable-5", "reasoning_effort": null}'),
]


def _messages_reply(mock_anthropic: MagicMock, text: str) -> None:
    response = MagicMock()
    response.content = [MagicMock(type="text", text=text)]
    mock_anthropic.return_value.messages.create.return_value = response


def _chat_reply(mock_openai: MagicMock, text: str) -> None:
    client = mock_openai.return_value
    client.with_options.return_value = client
    client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content=text))]


def _assert_routing_product(headers: dict[str, str]) -> None:
    # `slack_app` would bill the customer; the classifiers must stay on the unbilled product.
    assert headers["X-PostHog-Product"] == "slack_app_routing"
    assert json.loads(headers["X-PostHog-Properties"])["ai_product"] == "slack_app_routing"


class TestClassifierGatewayRouting:
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.Anthropic")
    def test_needs_repo_uses_go_messages_route_when_configured(self, mock_anthropic, _mock_httpx):
        _messages_reply(mock_anthropic, '{"needs_repo": true}')
        with override_settings(**GO_GATEWAY):
            assert _classify_needs_repo() is True

        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["base_url"] == "https://ai-gateway.example"
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        _assert_routing_product(kwargs["default_headers"])

    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.Anthropic")
    def test_needs_repo_falls_back_to_python_route_when_unset(self, mock_anthropic, _mock_httpx):
        _messages_reply(mock_anthropic, '{"needs_repo": true}')
        with override_settings(**PYTHON_GATEWAY):
            assert _classify_needs_repo() is True

        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["base_url"] == f"{LLM_GATEWAY_URL}/slack_app_routing"
        assert kwargs["api_key"] == LLM_GATEWAY_KEY

    @parameterized.expand(OPENAI_CLASSIFIERS)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_openai_classifier_uses_go_route_when_configured(self, _name, classify, reply, mock_openai, _mock_httpx):
        _chat_reply(mock_openai, reply)
        with override_settings(**GO_GATEWAY):
            assert classify()

        kwargs = mock_openai.call_args.kwargs
        assert kwargs["base_url"] == AI_GATEWAY_URL
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        _assert_routing_product(kwargs["default_headers"])

    @parameterized.expand(OPENAI_CLASSIFIERS)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_openai_classifier_falls_back_to_python_route_when_unset(
        self, _name, classify, reply, mock_openai, _mock_httpx
    ):
        _chat_reply(mock_openai, reply)
        with override_settings(**PYTHON_GATEWAY):
            assert classify()

        kwargs = mock_openai.call_args.kwargs
        assert kwargs["base_url"] == f"{LLM_GATEWAY_URL}/slack_app_routing/v1"
        assert kwargs["api_key"] == LLM_GATEWAY_KEY
