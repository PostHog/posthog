from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.salesforce.template_salesforce import (
    template_create as template_salesforce_create,
    template_update as template_salesforce_update,
    TemplatSalesforceMigrator,
)
from posthog.models import PluginConfig
from posthog.test.base import BaseTest


class TestTemplateSalesforceCreate(BaseHogFunctionTemplateTest):
    template = template_salesforce_create

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "instance_url": "https://example.my.salesforce.com",
                "access_token": "oauth-1234",
            },
            "path": "Contact",
            "properties": {
                "foo": "bar",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
                {
                    "body": {"foo": "bar"},
                    "method": "POST",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )

    def test_add_all_event_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_event_properties=True))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
                {
                    "body": {"$current_url": "https://example.com", "foo": "bar"},
                    "method": "POST",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )

    def test_add_all_person_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_person_properties=True))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
                {
                    "body": {"email": "example@posthog.com", "foo": "bar"},
                    "method": "POST",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )


class TestTemplateSalesforceUpdate(BaseHogFunctionTemplateTest):
    template = template_salesforce_update

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "instance_url": "https://example.my.salesforce.com",
                "access_token": "oauth-1234",
            },
            "path": "Lead/Email/example@posthog.com",
            "properties": {
                "foo": "bar",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
                {
                    "body": {"foo": "bar"},
                    "method": "PATCH",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )

    def test_add_all_event_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_event_properties=True))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
                {
                    "body": {"$current_url": "https://example.com", "foo": "bar"},
                    "method": "PATCH",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )

    def test_add_all_person_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_person_properties=True))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
                {
                    "body": {"email": "example@posthog.com", "foo": "bar"},
                    "method": "PATCH",
                    "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
                },
            )
        )


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "eventsToInclude": "a,b",
            "eventPath": "ignored",
            "eventMethodType": "POST",
            "propertiesToInclude": "email,$browser",
            "eventEndpointMapping": "",  # ignored
            "fieldMappings": "",  # ignored
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_default_config(self):
        obj = self.get_plugin_config({})
        template = TemplatSalesforceMigrator.migrate(obj)
        assert template["inputs"] == snapshot({"path": {"value": "ignored"}})
        assert template["filters"] == {
            "events": [
                {"id": "a", "name": "a", "order": 0, "type": "events"},
                {"id": "b", "name": "b", "order": 0, "type": "events"},
            ]
        }

    #
    # def test_disable_geoip(self):
    #     obj = self.get_plugin_config({"disable_geoip": "Yes"})
    #     template = TemplatSalesforceMigrator.migrate(obj)
    #     assert template["inputs"] == snapshot(
    #         {
    #             "host": {"value": "us.i.example.com"},
    #             "token": {"value": "apikey"},
    #             "include_all_properties": {"value": True},
    #             "properties": {"value": {"$geoip_disable": True}},
    #         }
    #     )
    #     assert template["filters"] == {}
    #
    # def test_ignore_events(self):
    #     obj = self.get_plugin_config({"events_to_ignore": "event1, event2, 'smore"})
    #     template = TemplatSalesforceMigrator.migrate(obj)
    #     assert template["inputs"] == snapshot(
    #         {
    #             "host": {"value": "us.i.example.com"},
    #             "token": {"value": "apikey"},
    #             "include_all_properties": {"value": True},
    #             "properties": {"value": {}},
    #         }
    #     )
    #     assert template["filters"] == {
    #         "events": [
    #             {
    #                 "id": None,
    #                 "name": "All events",
    #                 "type": "events",
    #                 "order": 0,
    #                 "properties": [{"type": "hogql", "key": "event not in ('event1', 'event2', '\\'smore')"}],
    #             }
    #         ]
    #     }
