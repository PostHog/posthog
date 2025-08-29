import pytest
from posthog.test.base import BaseTest

from inline_snapshot import snapshot

from posthog.cdp.templates.customerio.template_customerio import (
    TemplateCustomerioMigrator,
    template as template_customerio,
)
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.models.plugin import PluginConfig

from common.hogvm.python.utils import UncaughtHogVMException


def create_inputs(**kwargs):
    inputs = {
        "site_id": "SITE_ID",
        "token": "TOKEN",
        "host": "track.customer.io",
        "action": "automatic",
        "include_all_properties": False,
        "identifier_key": "email",
        "identifier_value": "example@posthog.com",
        "attributes": {"name": "example"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateCustomerio(BaseHogFunctionTemplateTest):
    template = template_customerio

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$pageview", "properties": {"url": "https://example.com"}},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://track.customer.io/api/v2/entity",
                {
                    "method": "POST",
                    "headers": {
                        "User-Agent": "PostHog Customer.io App",
                        "Authorization": "Basic U0lURV9JRDpUT0tFTg==",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "type": "person",
                        "action": "page",
                        "name": None,
                        "identifiers": {"email": "example@posthog.com"},
                        "attributes": {"name": "example"},
                        "timestamp": 1704067200,
                    },
                },
            )
        )

    def test_will_truncate_long_values(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {"event": "$pageview", "properties": {"url": "https://example.com/" + "12345" * 200}},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://track.customer.io/api/v2/entity",
                {
                    "method": "POST",
                    "headers": {
                        "User-Agent": "PostHog Customer.io App",
                        "Authorization": "Basic U0lURV9JRDpUT0tFTg==",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "type": "person",
                        "action": "page",
                        "name": None,
                        "identifiers": {"email": "example@posthog.com"},
                        "attributes": {
                            "url": "https://example.com/12345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345123451234512345",
                            "name": "example",
                        },
                        "timestamp": 1704067200,
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(inputs=create_inputs(include_all_properties=False))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot({"name": "example"})

        self.run_function(inputs=create_inputs(include_all_properties=True))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot(
            {"$current_url": "https://example.com", "name": "example"}
        )

        self.run_function(inputs=create_inputs(include_all_properties=True, action="identify"))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot(
            {"email": "example@posthog.com", "name": "example"}
        )

    def test_automatic_action_mapping(self):
        for event_name, expected_action in [
            ("$identify", "identify"),
            ("$set", "identify"),
            ("$pageview", "page"),
            ("$screen", "screen"),
            ("$autocapture", "event"),
            ("custom", "event"),
        ]:
            self.run_function(
                inputs=create_inputs(),
                globals={
                    "event": {"event": event_name, "properties": {"url": "https://example.com"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["action"] == expected_action

    def test_enforced_action(self):
        for event_name in [
            "$identify",
            "$pageview",
            "$screen",
            "$autocapture",
            "custom",
        ]:
            self.run_function(
                inputs=create_inputs(action="event"),
                globals={
                    "event": {"event": event_name, "properties": {"url": "https://example.com"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["action"] == "event"
            assert self.get_mock_fetch_calls()[0][1]["body"]["name"] == event_name

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(identifier_key="email", identifier_value=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No identifier set. Skipping as identifier is required.",)])

    def test_function_errors_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "error"}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=create_inputs())
        assert e.value.message == "Error from customer.io api: 400: {'error': 'error'}"


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "host": "track.customer.io",
            "eventsToSend": "",
            "customerioToken": "TOKEN",
            "customerioSiteId": "SITE_ID",
            "sendEventsFromAnonymousUsers": "Send all events",
            "identifyByEmail": "No",
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_full_function(self):
        obj = self.get_plugin_config({})

        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "action": {"value": "automatic"},
                "site_id": {"value": "SITE_ID"},
                "token": {"value": "TOKEN"},
                "host": {"value": "track.customer.io"},
                "identifier_key": {"value": "id"},
                "identifier_value": {"value": "{event.distinct_id}"},
                "include_all_properties": {"value": True},
                "attributes": {"value": {}},
            }
        )
        assert template["filters"] == snapshot({})

    def test_anon_config_send_all(self):
        obj = self.get_plugin_config(
            {
                "sendEventsFromAnonymousUsers": "Send all events",
            }
        )

        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["filters"] == snapshot({})

    def test_anon_config_send_emails(self):
        obj = self.get_plugin_config(
            {
                "sendEventsFromAnonymousUsers": "Only send events from users with emails",
            }
        )

        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["filters"] == snapshot(
            {"properties": [{"key": "email", "value": "is_set", "operator": "is_set", "type": "person"}]}
        )

    def test_anon_config_send_identified(self):
        obj = self.get_plugin_config(
            {
                "sendEventsFromAnonymousUsers": "Only send events from users that have been identified",
            }
        )

        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["filters"] == snapshot(
            {"properties": [{"key": "$is_identified", "value": ["true"], "operator": "exact", "type": "event"}]}
        )

    def test_identify_by_email(self):
        obj = self.get_plugin_config({"identifyByEmail": "Yes"})
        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["inputs"]["identifier_key"] == {"value": "email"}
        assert template["inputs"]["identifier_value"] == {"value": "{person.properties.email}"}

    def test_events_filters(self):
        obj = self.get_plugin_config({"eventsToSend": "event1,event2, $pageview"})
        template = TemplateCustomerioMigrator.migrate(obj)
        assert template["filters"] == snapshot(
            {
                "events": [
                    {"id": "event1", "name": "event1", "type": "events", "order": 0},
                    {"id": "event2", "name": "event2", "type": "events", "order": 0},
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                ]
            }
        )
