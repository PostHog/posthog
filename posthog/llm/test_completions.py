from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from posthog.llm.completions import hit_openai


class TestHitOpenai(SimpleTestCase):
    @override_settings(OPENAI_MODEL="my-gateway-deployment")
    @patch("posthog.llm.completions._get_openai_client")
    def test_sends_the_configured_model(self, mock_get_client: MagicMock) -> None:
        create = mock_get_client.return_value.chat.completions.create
        create.return_value.choices = [MagicMock(message=MagicMock(content="SELECT 1;"))]
        create.return_value.usage.prompt_tokens = 1
        create.return_value.usage.completion_tokens = 2

        completion = hit_openai(messages=[{"role": "user", "content": "hi"}], user="test")

        assert create.call_args.kwargs["model"] == "my-gateway-deployment"
        assert completion.content == "SELECT 1"
