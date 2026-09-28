import pytest

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.zendesk.template_zendesk import template as template_zendesk


def create_inputs(**kwargs):
    inputs = {
        "subdomain": "zendeskhelp",
        "admin_email": "admin@zendesk.com",
        "token": "Q0UlvCexisMu6Je5MHG72ev16Tz68Tw8PRRpb5SX",
        "email": "max@posthog.com",
        "name": "Max",
        "attributes": {"phone": "0123456789", "plan": "starship-enterprise"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateZendesk(BaseHogFunctionTemplateTest):
    template = template_zendesk

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
            },
        )

        assert self.get_mock_fetch_calls()[0] == (
            "https://zendeskhelp.zendesk.com/api/v2/users/create_or_update",
            {
                "method": "POST",
                "headers": {
                    "Authorization": "Basic YWRtaW5AemVuZGVzay5jb20vdG9rZW46UTBVbHZDZXhpc011NkplNU1IRzcyZXYxNlR6NjhUdzhQUlJwYjVTWA==",
                    "Content-Type": "application/json",
                },
                "body": {
                    "user": {
                        "email": "max@posthog.com",
                        "name": "Max",
                        "user_fields": {"phone": "0123456789", "plan": "starship-enterprise"},
                        "skip_verify_email": True,
                    }
                },
            },
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(name=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("`email` or `name` input is empty. Not creating a contact.",)]

        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("`email` or `name` input is empty. Not creating a contact.",)]

    def test_function_uses_the_connected_account(self):
        self.run_function(
            inputs=create_inputs(
                subdomain="", admin_email="", token="", oauth={"subdomain": "acme", "access_token": "at_1"}
            ),
        )

        url, request = self.get_mock_fetch_calls()[0]
        assert url == "https://acme.zendesk.com/api/v2/users/create_or_update"
        assert request["headers"]["Authorization"] == "Bearer at_1"

    def test_function_without_credentials_raises(self):
        with pytest.raises(Exception, match="Connect a Zendesk account"):
            self.run_function(inputs=create_inputs(token=""))

        assert not self.get_mock_fetch_calls()
