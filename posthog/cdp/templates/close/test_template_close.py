import base64

from posthog.cdp.templates.close.template_close import template as template_close
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "email": "max@posthog.com",
        "leadName": "PostHog",
        "contactAttributes": {"name": "Max", "title": "Mascot"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateClose(BaseHogFunctionTemplateTest):
    template = template_close

    def _expected_auth(self):
        return "Basic " + base64.b64encode(b"apikey12345:").decode("utf-8")

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_inputs())
        assert self.get_mock_fetch_calls()[0] == (
            "https://api.close.com/api/v1/lead/",
            {
                "body": {
                    "contacts": [
                        {
                            "emails": [{"email": "max@posthog.com", "type": "office"}],
                            "name": "Max",
                            "title": "Mascot",
                        }
                    ],
                    "name": "PostHog",
                },
                "method": "POST",
                "headers": {
                    "Authorization": self._expected_auth(),
                    "Content-Type": "application/json",
                },
            },
        )

    def test_ignores_empty_contact_attributes(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_inputs(contactAttributes={"name": "Max", "title": ""}))
        assert self.get_mock_fetch_calls()[0] == (
            "https://api.close.com/api/v1/lead/",
            {
                "body": {
                    "contacts": [
                        {
                            "emails": [{"email": "max@posthog.com", "type": "office"}],
                            "name": "Max",
                        }
                    ],
                    "name": "PostHog",
                },
                "method": "POST",
                "headers": {
                    "Authorization": self._expected_auth(),
                    "Content-Type": "application/json",
                },
            },
        )

    def test_omits_lead_name_when_empty(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_inputs(leadName=""))
        assert self.get_mock_fetch_calls()[0][1]["body"] == {
            "contacts": [
                {
                    "emails": [{"email": "max@posthog.com", "type": "office"}],
                    "name": "Max",
                    "title": "Mascot",
                }
            ],
        }

    def test_raises_on_error_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "bad request"}}  # type: ignore
        with self.assertRaises(Exception) as e:
            self.run_function(inputs=create_inputs())
        assert "Error from api.close.com (status 400)" in str(e.exception)
