import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.llm.completions import hit_openai

AI_GATEWAY_URL = "https://ai-gateway.example/v1"
AI_GATEWAY_KEY = "phs_project_secret"
PROPERTIES = {"ai_product": "hogql", "ai_feature": "draft_sql", "$ai_billable": True, "team_id": 42}


def _stub_create(client: MagicMock) -> MagicMock:
    create = client.chat.completions.create
    create.return_value.choices = [MagicMock(message=MagicMock(content="SELECT 1;"))]
    create.return_value.usage.prompt_tokens = 1
    create.return_value.usage.completion_tokens = 2
    return create


class TestHitOpenai(SimpleTestCase):
    @parameterized.expand([("my-gateway-deployment", None), ("gpt-5-chat-latest", None), ("gpt-6-luna", "low")])
    @patch("posthog.llm.completions._get_openai_client")
    def test_sends_the_configured_model(
        self, model: str, expected_effort: str | None, mock_get_client: MagicMock
    ) -> None:
        create = _stub_create(mock_get_client.return_value)

        with override_settings(OPENAI_MODEL=model, AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""):
            completion = hit_openai(messages=[{"role": "user", "content": "hi"}], user="test")

        assert create.call_args.kwargs["model"] == model
        assert create.call_args.kwargs.get("reasoning_effort") == expected_effort
        assert "temperature" not in create.call_args.kwargs
        assert completion.content == "SELECT 1"

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.completions._get_openai_client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_gateway_route_sends_labels_instead_of_capture_kwargs(
        self, mock_gateway_openai: MagicMock, mock_get_direct_client: MagicMock
    ) -> None:
        create = _stub_create(mock_gateway_openai.return_value)

        completion = hit_openai(
            messages=[{"role": "user", "content": "hi"}],
            user="US/1",
            posthog_properties=PROPERTIES,
            posthog_groups={"instance": "https://us.posthog.com"},
            distinct_id="user-distinct-id",
        )

        headers = mock_gateway_openai.call_args.kwargs["default_headers"]
        assert headers["X-PostHog-Product"] == "hogql"
        assert headers["X-PostHog-Distinct-Id"] == "user-distinct-id"
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "hogql",
            "ai_feature": "draft_sql",
            "team_id": "42",
        }
        assert not {key for key in create.call_args.kwargs if key.startswith("posthog_")}
        assert completion.content == "SELECT 1"
        mock_get_direct_client.assert_not_called()

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    @patch("posthog.llm.completions._get_openai_client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_falls_back_to_the_direct_client_when_gateway_unset(
        self, mock_gateway_openai: MagicMock, mock_get_direct_client: MagicMock
    ) -> None:
        create = _stub_create(mock_get_direct_client.return_value)

        hit_openai(
            messages=[{"role": "user", "content": "hi"}],
            user="US/1",
            posthog_properties=PROPERTIES,
            distinct_id="user-distinct-id",
        )

        assert create.call_args.kwargs["posthog_properties"] == PROPERTIES
        assert create.call_args.kwargs["posthog_distinct_id"] == "user-distinct-id"
        mock_gateway_openai.assert_not_called()
