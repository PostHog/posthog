from posthog.test.base import BaseTest

from inline_snapshot import snapshot

from posthog.cdp.templates.avo.template_avo import (
    TemplateAvoMigrator,
    template as template_avo,
)
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.models import PluginConfig


class TestTemplateAvo(BaseHogFunctionTemplateTest):
    template = template_avo

    def _inputs(self, **kwargs):
        inputs = {
            "apiKey": "NnBd7B55ZXC6o0Kh20pE",
            "environment": "dev",
            "appName": "PostHog",
            "excludeProperties": "",
            "includeProperties": "",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "event": {
                    "uuid": "0191c693-d93b-7516-b1e3-64ec33c96464",
                    "distinct_id": "66e614bd-d9f2-491e-9e2c-eeab3090f72f",
                    "event": "sign up",
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
            # (None, "null"),
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
                    "event": {"event": "sign up", "properties": {"test": property_value}},
                },
            )

            res = self.get_mock_fetch_calls()[0]
            assert res[1]["body"][0]["eventProperties"][0]["propertyType"] == expected_type

    def test_property_filters(self):
        # [excludeProperties, includeProperties], expected properties array
        for filters, expected_result in [
            [["name", ""], ["company", "job"]],
            [[" name ", ""], ["company", "job"]],
            [["name", "name"], []],
            [["", "name,company"], ["name", "company"]],
        ]:
            self.run_function(
                inputs={
                    "apiKey": "NnBd7B55ZXC6o0Kh20pE",
                    "environment": "dev",
                    "appName": "PostHog",
                    "excludeProperties": filters[0],
                    "includeProperties": filters[1],
                },
                globals={
                    "event": {
                        "event": "sign up",
                        "properties": {"name": "Max", "company": "PostHog", "job": "Product Engineer"},
                    },
                },
            )

            res = self.get_mock_fetch_calls()[0][1]["body"][0]["eventProperties"]
            assert [item["propertyName"] for item in res] == expected_result


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "avoApiKey": "1234567890",
            "environment": "dev",
            "appName": "PostHog",
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_default_config(self):
        obj = self.get_plugin_config(
            {"excludeProperties": "price, currency", "includeProperties": "account_status, plan"}
        )
        template = TemplateAvoMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "apiKey": {"value": "1234567890"},
                "environment": {"value": "dev"},
                "appName": {"value": "PostHog"},
                "excludeProperties": {"value": "price, currency"},
                "includeProperties": {"value": "account_status, plan"},
            }
        )
        assert template["filters"] == {"events": []}

    def test_include_events(self):
        obj = self.get_plugin_config({"includeEvents": "sign up,page view"})
        template = TemplateAvoMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "apiKey": {"value": "1234567890"},
                "environment": {"value": "dev"},
                "appName": {"value": "PostHog"},
                "excludeProperties": {"value": ""},
                "includeProperties": {"value": ""},
            }
        )
        assert template["filters"] == {
            "events": [
                {"id": "sign up", "name": "sign up", "type": "events", "order": 0},
                {"id": "page view", "name": "page view", "type": "events", "order": 0},
            ]
        }

    def test_exclude_events(self):
        obj = self.get_plugin_config({"excludeEvents": "sign up,page view"})
        template = TemplateAvoMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "apiKey": {"value": "1234567890"},
                "environment": {"value": "dev"},
                "appName": {"value": "PostHog"},
                "excludeProperties": {"value": ""},
                "includeProperties": {"value": ""},
            }
        )
        assert template["filters"] == {
            "events": [
                {
                    "id": None,
                    "name": "All events",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "event not in ('sign up', 'page view')", "type": "hogql"}],
                },
            ]
        }

    def test_include_and_exclude_events(self):
        obj = self.get_plugin_config(
            {"excludeEvents": "page view, log in,page leave", "includeEvents": "sign up,page view"}
        )
        template = TemplateAvoMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "apiKey": {"value": "1234567890"},
                "environment": {"value": "dev"},
                "appName": {"value": "PostHog"},
                "excludeProperties": {"value": ""},
                "includeProperties": {"value": ""},
            }
        )
        assert template["filters"] == {
            "events": [
                {"id": "sign up", "name": "sign up", "type": "events", "order": 0},
                {"id": "page view", "name": "page view", "type": "events", "order": 0},
            ]
        }
