from inline_snapshot import snapshot

from posthog.cdp.templates.activecampaign.template_activecampaign import template as template_activecampaign
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


def create_inputs(**kwargs):
    inputs = {
        "accountName": "posthog",
        "apiKey": "API_KEY",
        "email": "max@posthog.com",
        "firstName": "max",
        "attributes": {"1": "PostHog", "2": "posthog.com"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateActiveCampaign(BaseHogFunctionTemplateTest):
    template = template_activecampaign

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://posthog.api-us1.com/api/3/contact/sync",
                {
                    "method": "POST",
                    "headers": {
                        "content-type": "application/json",
                        "Api-Token": "API_KEY",
                    },
                    "body": {
                        "contact": {
                            "email": "max@posthog.com",
                            "firstName": "max",
                            "fieldValues": [{"field": "1", "value": "PostHog"}, {"field": "2", "value": "posthog.com"}],
                        }
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("`email` input is empty. Not creating a contact.",)])
