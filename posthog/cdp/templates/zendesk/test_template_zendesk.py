from inline_snapshot import snapshot

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

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
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
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(name=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("`email` or `name` input is empty. Not creating a contact.",)])

        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("`email` or `name` input is empty. Not creating a contact.",)])
