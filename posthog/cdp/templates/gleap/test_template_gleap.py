from inline_snapshot import snapshot

from posthog.cdp.templates.gleap.template_gleap import template as template_gleap
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "uB6Jymn60NN5EEIWgiUzZx13geVlEx26",
        "include_all_properties": False,
        "userId": "edad9282-25d0-4cf1-af0e-415535ee1161",
        "attributes": {"name": "example", "email": "example@posthog.com"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateGleap(BaseHogFunctionTemplateTest):
    template = template_gleap

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.gleap.io/admin/identify",
                {
                    "method": "POST",
                    "headers": {
                        "User-Agent": "PostHog Gleap.io App",
                        "Api-Token": "uB6Jymn60NN5EEIWgiUzZx13geVlEx26",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "userId": "edad9282-25d0-4cf1-af0e-415535ee1161",
                        "name": "example",
                        "email": "example@posthog.com",
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=False),
            globals={
                "person": {"properties": {"account_status": "paid"}},
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"] == snapshot(
            {"userId": "edad9282-25d0-4cf1-af0e-415535ee1161", "name": "example", "email": "example@posthog.com"}
        )

        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "person": {"properties": {"account_status": "paid"}},
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"] == snapshot(
            {
                "userId": "edad9282-25d0-4cf1-af0e-415535ee1161",
                "account_status": "paid",
                "name": "example",
                "email": "example@posthog.com",
            }
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(userId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No User ID set. Skipping...",)])
