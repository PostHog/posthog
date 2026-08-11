import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch


def _completion(payload: dict) -> MagicMock:
    completion = MagicMock()
    completion.choices[0].message.content = json.dumps(payload)
    return completion


class TestAiRegex(APIBaseTest):
    def _post(self, body: dict) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/ai/regex",
            body,
        )

    @patch("posthog.session_recordings.session_recording_api.get_openai_client")
    def test_retries_once_when_the_model_refuses(self, mock_get_client: MagicMock) -> None:
        parse = mock_get_client.return_value.beta.chat.completions.parse
        parse.side_effect = [
            _completion({"result": "error", "data": {"output": "some refusal"}}),
            _completion({"result": "success", "data": {"output": "app\\.posthog\\.com/auth"}}),
        ]

        response = self._post({"regex": "urls that include app.posthog.com/auth"})

        assert response.status_code == 200
        assert response.json() == {"result": "success", "data": {"output": "app\\.posthog\\.com/auth"}}
        assert parse.call_count == 2

    @patch("posthog.session_recordings.session_recording_api.get_openai_client")
    def test_returns_the_error_when_the_retry_also_refuses(self, mock_get_client: MagicMock) -> None:
        parse = mock_get_client.return_value.beta.chat.completions.parse
        parse.side_effect = [
            _completion({"result": "error", "data": {"output": "off-topic"}}),
            _completion({"result": "error", "data": {"output": "off-topic"}}),
        ]

        response = self._post({"regex": "what is the weather"})

        assert response.status_code == 200
        assert response.json()["result"] == "error"
        assert parse.call_count == 2

    @patch("posthog.session_recordings.session_recording_api.get_openai_client")
    def test_re2_surface_forbids_lookahead_in_the_prompt(self, mock_get_client: MagicMock) -> None:
        parse = mock_get_client.return_value.beta.chat.completions.parse
        parse.return_value = _completion({"result": "success", "data": {"output": "/users/\\d+"}})

        self._post({"regex": "the id in /users/123", "engine": "re2"})

        system_content = parse.call_args.kwargs["messages"][0]["content"]
        assert "RE2" in system_content
        assert "javascript" not in system_content.lower()

    @patch("posthog.session_recordings.session_recording_api.get_openai_client")
    def test_default_surface_allows_lookahead_in_the_prompt(self, mock_get_client: MagicMock) -> None:
        parse = mock_get_client.return_value.beta.chat.completions.parse
        parse.return_value = _completion({"result": "success", "data": {"output": "^(?!.*auth).*$"}})

        self._post({"regex": "pages that are not the auth page"})

        system_content = parse.call_args.kwargs["messages"][0]["content"]
        assert "lookahead is allowed" in system_content
