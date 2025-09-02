from inline_snapshot import snapshot

from posthog.cdp.templates.attio.template_attio import template as template_attio
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "email": "max@posthog.com",
        "personAttributes": {"name": "Max", "job_title": "Mascot"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateAttio(BaseHogFunctionTemplateTest):
    template = template_attio

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
                {
                    "body": {
                        "data": {
                            "values": {
                                "email_addresses": [{"email_address": "max@posthog.com"}],
                                "name": "Max",
                                "job_title": "Mascot",
                            }
                        }
                    },
                    "method": "PUT",
                    "headers": {
                        "Authorization": "Bearer apikey12345",
                        "Content-Type": "application/json",
                    },
                },
            )
        )

    def test_ignores_empty_values(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_inputs(personAttributes={"name": "Max", "job_title": ""}))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
                {
                    "body": {
                        "data": {
                            "values": {
                                "email_addresses": [{"email_address": "max@posthog.com"}],
                                "name": "Max",
                            }
                        }
                    },
                    "method": "PUT",
                    "headers": {
                        "Authorization": "Bearer apikey12345",
                        "Content-Type": "application/json",
                    },
                },
            )
        )
