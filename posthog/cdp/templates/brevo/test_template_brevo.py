from inline_snapshot import snapshot

from posthog.cdp.templates.brevo.template_brevo import template as template_brevo
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "email": "max@posthog.com",
        "attributes": {"EMAIL": "max@posthog.com", "FIRSTNAME": "Max"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateBrevo(BaseHogFunctionTemplateTest):
    template = template_brevo

    def test_function_works(self):
        self.run_function(inputs=create_inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.brevo.com/v3/contacts",
                {
                    "method": "POST",
                    "headers": {
                        "api-key": "apikey12345",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "updateEnabled": True,
                        "attributes": {"EMAIL": "max@posthog.com", "FIRSTNAME": "Max"},
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])
