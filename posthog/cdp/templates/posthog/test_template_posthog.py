from posthog.test.base import BaseTest

from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.posthog.template_posthog import (
    TemplatePostHogMigrator,
    template as template_posthog,
)
from posthog.models import PluginConfig


class TestTemplatePosthog(BaseHogFunctionTemplateTest):
    template = template_posthog

    def test_function_works(self):
        self.run_function(
            inputs={
                "host": "https://us.i.posthog.com",
                "token": "TOKEN",
                "include_all_properties": True,
                "properties": {"additional": "value"},
            }
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://us.i.posthog.com/e",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "token": "TOKEN",
                        "elements_chain": "",
                        "event": "event-name",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "distinct_id": "distinct-id",
                        "properties": {"$current_url": "https://example.com", "additional": "value"},
                    },
                },
            )
        )

    def test_function_doesnt_include_all_properties(self):
        self.run_function(
            inputs={
                "host": "https://us.i.posthog.com",
                "token": "TOKEN",
                "include_all_properties": False,
                "properties": {"additional": "value"},
            }
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == snapshot({"additional": "value"})


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "host": "us.i.example.com",
            "replication": "ignored",
            "events_to_ignore": "",
            "project_api_key": "apikey",
            "disable_geoip": False,
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_default_config(self):
        obj = self.get_plugin_config({})
        template = TemplatePostHogMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "host": {"value": "us.i.example.com"},
                "token": {"value": "apikey"},
                "include_all_properties": {"value": True},
                "properties": {"value": {}},
            }
        )
        assert template["filters"] == {}

    def test_disable_geoip(self):
        obj = self.get_plugin_config({"disable_geoip": "Yes"})
        template = TemplatePostHogMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "host": {"value": "us.i.example.com"},
                "token": {"value": "apikey"},
                "include_all_properties": {"value": True},
                "properties": {"value": {"$geoip_disable": True}},
            }
        )
        assert template["filters"] == {}

    def test_ignore_events(self):
        obj = self.get_plugin_config({"events_to_ignore": "event1, event2, 'smore"})
        template = TemplatePostHogMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "host": {"value": "us.i.example.com"},
                "token": {"value": "apikey"},
                "include_all_properties": {"value": True},
                "properties": {"value": {}},
            }
        )
        assert template["filters"] == {
            "events": [
                {
                    "id": None,
                    "name": "All events",
                    "type": "events",
                    "order": 0,
                    "properties": [{"type": "hogql", "key": "event not in ('event1', 'event2', '\\'smore')"}],
                }
            ]
        }
