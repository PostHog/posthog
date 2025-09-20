from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.mailchimp.template_mailchimp import template as template_mailchimp


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "abcdef",
        "audienceId": "a1b2c3",
        "dataCenterId": "us1",
        "email": "max@posthog.com",
        "include_all_properties": False,
        "doubleOptIn": False,
        "properties": {"FNAME": "Max", "LNAME": "AI", "COMPANY": "PostHog"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateMailchimp(BaseHogFunctionTemplateTest):
    template = template_mailchimp

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://us1.api.mailchimp.com/3.0/lists/a1b2c3/members/12d91149f17f7ac265e833ea05ef6249",
                {
                    "method": "GET",
                    "headers": {
                        "Authorization": "Bearer abcdef",
                        "Content-Type": "application/json",
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=False),
            globals={
                "event": {"properties": {"PHONE": "+1415000000"}},
            },
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["merge_fields"] == snapshot(
            {"FNAME": "Max", "LNAME": "AI", "COMPANY": "PostHog"}
        )

        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {"properties": {"PHONE": "+1415000000"}},
            },
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["merge_fields"] == snapshot(
            {
                "FNAME": "Max",
                "LNAME": "AI",
                "COMPANY": "PostHog",
                "PHONE": "+1415000000",
            }
        )

    def test_double_opt_in(self):
        self.run_function(
            inputs=create_inputs(doubleOptIn=False),
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["status_if_new"] == snapshot("subscribed")

        self.run_function(
            inputs=create_inputs(doubleOptIn=True),
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["status_if_new"] == snapshot("pending")

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])

    def test_email_case_normalization(self):
        # Test with lowercase email
        self.run_function(
            inputs=create_inputs(email="max@posthog.com"),
        )
        lowercase_url = self.get_mock_fetch_calls()[0][0]

        # Test with mixed case email
        self.run_function(
            inputs=create_inputs(email="Max@Posthog.com"),
        )
        mixed_case_url = self.get_mock_fetch_calls()[0][0]

        # Verify both URLs are identical since email is normalized to lowercase
        assert lowercase_url == mixed_case_url
