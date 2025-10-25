from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.knock.template_knock import template as template_knock


def create_inputs(**kwargs):
    inputs = {
        "webhookUrl": "https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp",
        "include_all_properties": False,
        "userId": "edad9282-25d0-4cf1-af0e-415535ee1161",
        "attributes": {"phone": "0123456789"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateKnock(BaseHogFunctionTemplateTest):
    template = template_knock

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                        "phone": "0123456789",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "type": "track",
                        "event": "$pageview",
                        "userId": "edad9282-25d0-4cf1-af0e-415535ee1161",
                        "properties": {"phone": "0123456789"},
                        "messageId": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                        "timestamp": "2024-09-16T16:11:48.577Z",
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=False),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == snapshot({"phone": "0123456789"})

        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == snapshot(
            {
                "price": 15,
                "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                "$browser": "Chrome",
                "phone": "0123456789",
            }
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(userId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No User ID set. Skipping...",)])
