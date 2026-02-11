import pytest

from posthog.cdp.templates.cursor.template_cursor import template as template_cursor
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


class TestTemplateCursor(BaseHogFunctionTemplateTest):
    template = template_cursor

    def _inputs(self, **kwargs):
        inputs = {
            "cursor_account": {
                "api_key": "key_test123",
            },
            "repository": "https://github.com/posthog/posthog",
            "prompt": "Fix the bug in the login flow",
            "ref": "main",
            "auto_create_pr": True,
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert len(self.get_mock_fetch_calls()) == 1
        call = self.get_mock_fetch_calls()[0]
        assert call[0] == "https://api.cursor.com/v0/agents"
        assert call[1]["method"] == "POST"
        assert "Basic" in call[1]["headers"]["Authorization"]
        assert call[1]["body"]["prompt"]["text"] == "Fix the bug in the login flow"
        assert call[1]["body"]["source"]["repository"] == "https://github.com/posthog/posthog"
        assert call[1]["body"]["source"]["ref"] == "main"
        assert call[1]["body"]["target"]["autoCreatePr"] is True

    def test_function_without_ref(self):
        self.run_function(inputs=self._inputs(ref=""))

        call = self.get_mock_fetch_calls()[0]
        assert "ref" not in call[1]["body"]["source"]

    def test_function_raises_on_error(self):
        self.fetch_responses["https://api.cursor.com/v0/agents"] = {"status": 401, "body": "Unauthorized"}

        with pytest.raises(Exception) as e:
            self.run_function(inputs=self._inputs())
        assert "Failed to launch Cursor agent" in e.value.message  # type: ignore[attr-defined]
