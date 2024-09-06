from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.avo.template_avo import template as template_avo


class TestTemplateAvo(BaseHogFunctionTemplateTest):
    template = template_avo

    def _inputs(self, **kwargs):
        inputs = {"apiKey": "NnBd7B55ZXC6o0Kh20pE", "environment": "dev", "appName": "PostHog"}
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "event": {
                    "uuid": "0191c693-d93b-7516-b1e3-64ec33c96464",
                    "distinct_id": "66e614bd-d9f2-491e-9e2c-eeab3090f72f",
                    "name": "sign up",
                    "properties": {
                        "distinct_id": "66e614bd-d9f2-491e-9e2c-eeab3090f72f",
                        "token": "phc_ex7Mnvi4DqeB6xSQoXU1UVPzAmUIpicMFKELQXGGTYQO",
                        "bob": {"name": "bob"},
                        "age": 99,
                        "name": "bob",
                        "items": ["apple", "stick"],
                        "job": True,
                        "noop": None,
                        "test": 1.4,
                    },
                },
                "person": {
                    "properties": {"email": "max@posthog.com", "name": "Max", "company": "PostHog"},
                },
            },
        )

        res = self.get_mock_fetch_calls()[0]
        res[1]["body"][0]["sessionId"] = "4d4454b4-31bb-4b13-8167-4ec76a0f49b6"
        res[1]["body"][0]["createdAt"] = "2024-09-06T09:04:28.324Z"
        assert res == snapshot(
            (
                "https://api.avo.app/inspector/posthog/v1/track",
                {
                    "method": "POST",
                    "headers": {
                        "env": "dev",
                        "api-key": "NnBd7B55ZXC6o0Kh20pE",
                        "content-type": "application/json",
                        "accept": "application/json",
                    },
                    "body": [
                        {
                            "apiKey": "NnBd7B55ZXC6o0Kh20pE",
                            "env": "dev",
                            "appName": "PostHog",
                            "sessionId": "4d4454b4-31bb-4b13-8167-4ec76a0f49b6",
                            "createdAt": "2024-09-06T09:04:28.324Z",
                            "avoFunction": False,
                            "eventId": None,
                            "eventHash": None,
                            "appVersion": "1.0.0",
                            "libVersion": "1.0.0",
                            "libPlatform": "node",
                            "trackingId": "",
                            "samplingRate": 1,
                            "type": "event",
                            "eventName": "sign up",
                            "messageId": "0191c693-d93b-7516-b1e3-64ec33c96464",
                            "eventProperties": [
                                {"propertyName": "distinct_id", "propertyType": "string"},
                                {"propertyName": "token", "propertyType": "string"},
                                {"propertyName": "bob", "propertyType": "object"},
                                {"propertyName": "age", "propertyType": "int"},
                                {"propertyName": "name", "propertyType": "string"},
                                {"propertyName": "items", "propertyType": "list"},
                                {"propertyName": "job", "propertyType": "boolean"},
                                {"propertyName": "noop", "propertyType": "null"},
                                {"propertyName": "test", "propertyType": "float"},
                            ],
                        }
                    ],
                },
            )
        )

    def test_automatic_type_mapping(self):
        for property_value, expected_type in [
            (None, "null"),
            ("Bob", "string"),
            (99, "int"),
            (1.4, "float"),
            (True, "boolean"),
            ({"name": "Bob"}, "object"),
            ([1, 2, 3], "list"),
        ]:
            self.run_function(
                inputs=self._inputs(),
                globals={
                    "event": {"name": "sign up", "properties": {"test": property_value}},
                },
            )

            res = self.get_mock_fetch_calls()[0]
            assert res[1]["body"][0]["eventProperties"][0]["propertyType"] == expected_type
