import pytest

from products.cdp.backend.templates.helpers import BaseHogFunctionTemplateTest
from products.cdp.backend.templates.zendesk.template_zendesk import template as template_zendesk

from common.hogvm.python.utils import UncaughtHogVMException


def create_inputs(**kwargs):
    inputs = {
        "subdomain": "zendeskhelp",
        "client_id": "posthog_destination",
        "client_secret": "fake-client-secret",
        "email": "max@posthog.com",
        "name": "Max",
        "attributes": {"phone": "0123456789", "plan": "starship-enterprise"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateZendesk(BaseHogFunctionTemplateTest):
    template = template_zendesk

    def setUp(self):
        super().setUp()
        self.mock_fetch_response = lambda url, *args: (  # type: ignore
            {"status": 200, "body": {"access_token": "fake-access-token", "token_type": "bearer"}}
            if url.endswith("/oauth/tokens")
            else {"status": 200, "body": {"user": {"id": 1}}}
        )

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
            },
        )

        assert self.get_mock_fetch_calls() == [
            (
                "https://zendeskhelp.zendesk.com/oauth/tokens",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "grant_type": "client_credentials",
                        "client_id": "posthog_destination",
                        "client_secret": "fake-client-secret",
                        "scope": "users:write",
                        "expires_in": 300,
                    },
                },
            ),
            (
                "https://zendeskhelp.zendesk.com/api/v2/users/create_or_update",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer fake-access-token",
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
            ),
        ]

    def test_function_stops_when_token_request_fails(self):
        self.mock_fetch_response = lambda *args: {"status": 401, "body": {"error": "invalid_client"}}  # type: ignore

        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=create_inputs())

        assert e.value.message.startswith("Could not get an access token from zendeskhelp.zendesk.com (status 401)")
        assert len(self.get_mock_fetch_calls()) == 1

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(name=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("`email` or `name` input is empty. Not creating a contact.",)]

        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("`email` or `name` input is empty. Not creating a contact.",)]
