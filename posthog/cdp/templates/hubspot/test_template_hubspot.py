import pytest
from inline_snapshot import snapshot

from common.hogvm.python.utils import UncaughtHogVMException
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import (
    template as template_hubspot,
    template_event as template_hubspot_event,
    TemplateHubspotMigrator,
)
from posthog.models import PluginConfig
from posthog.test.base import BaseTest


class TestTemplateHubspot(BaseHogFunctionTemplateTest):
    template = template_hubspot

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {"access_token": "TOKEN"},
            "email": "example@posthog.com",
            "properties": {
                "company": "PostHog",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"status": "success"}}  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls() == [
            (
                "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "inputs": [
                            {
                                "properties": {"company": "PostHog", "email": "example@posthog.com"},
                                "id": "example@posthog.com",
                                "idProperty": "email",
                            }
                        ]
                    },
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Contact example@posthog.com updated successfully!",)]

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Not creating a contact.",)]


EVENT_DEFINITION_RESPONSE = {
    "status": 200,
    "body": {
        "fullyQualifiedName": "pe_purchase",
        "properties": [
            {
                "name": "currency",
                "type": "string",
            },
            {
                "name": "price",
                "type": "number",
            },
            {
                "name": "product",
                "type": "string",
            },
        ],
    },
}


class TestTemplateHubspotEvent(BaseHogFunctionTemplateTest):
    template = template_hubspot_event

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {"access_token": "TOKEN"},
            "eventName": "purchase",
            "email": "example@posthog.com",
            "include_all_properties": False,
            "properties": {
                "price": 50,
                "currency": "USD",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: EVENT_DEFINITION_RESPONSE  # type: ignore

        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.hubapi.com/events/v3/send",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "eventName": "pe_purchase",
                        "email": "example@posthog.com",
                        "occurredAt": "2024-01-01T00:00:00Z",
                        "properties": {"price": 50, "currency": "USD"},
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.mock_fetch_response = lambda *args: EVENT_DEFINITION_RESPONSE  # type: ignore

        self.run_function(
            inputs=self._inputs(include_all_properties=False, event="purchase subscription"),
            globals={
                "event": {"properties": {"product": "CDP"}},
            },
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["properties"] == snapshot({"price": 50, "currency": "USD"})

        self.run_function(
            inputs=self._inputs(include_all_properties=True),
            globals={
                "event": {"event": "purchase subscription", "properties": {"product": "CDP"}},
            },
        )

        assert self.get_mock_fetch_calls()[1][1]["body"]["properties"] == snapshot(
            {"price": 50, "currency": "USD", "product": "CDP"}
        )

    def test_new_event_creation(self):
        self.fetch_responses = {
            "https://api.hubapi.com/events/v3/event-definitions/sign_up/?includeProperties=true": {
                "status": 400,
                "body": {"status": "error"},
            },
            "https://api.hubapi.com/events/v3/event-definitions": {
                "status": 200,
                "body": {"fullyQualifiedName": "pe_sign_up"},
            },
        }

        self.run_function(
            inputs=self._inputs(include_all_properties=True, eventName="sign_up"),
            globals={
                "event": {
                    "properties": {"price": 50, "currency": "USD", "expressDelivery": True},
                },
            },
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.hubapi.com/events/v3/event-definitions",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "label": "sign_up",
                        "name": "sign_up",
                        "description": "sign_up - (created by PostHog)",
                        "primaryObject": "CONTACT",
                        "propertyDefinitions": [
                            {
                                "name": "price",
                                "label": "price",
                                "type": "number",
                                "description": "price - (created by PostHog)",
                            },
                            {
                                "name": "currency",
                                "label": "currency",
                                "type": "string",
                                "description": "currency - (created by PostHog)",
                            },
                            {
                                "name": "expressDelivery",
                                "label": "expressDelivery",
                                "type": "enumeration",
                                "description": "expressDelivery - (created by PostHog)",
                                "options": [
                                    {
                                        "label": "true",
                                        "value": True,
                                        "hidden": False,
                                        "description": "True",
                                        "displayOrder": 1,
                                    },
                                    {
                                        "label": "false",
                                        "value": False,
                                        "hidden": False,
                                        "description": "False",
                                        "displayOrder": 2,
                                    },
                                ],
                            },
                        ],
                    },
                },
            )
        )

        assert self.get_mock_fetch_calls()[2] == snapshot(
            (
                "https://api.hubapi.com/events/v3/send",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "eventName": "pe_sign_up",
                        "email": "example@posthog.com",
                        "occurredAt": "2024-01-01T00:00:00Z",
                        "properties": {
                            "price": 50,
                            "currency": "USD",
                            "expressDelivery": True,
                        },
                    },
                },
            )
        )

    def test_new_property_creation(self):
        self.fetch_responses = {
            "https://api.hubapi.com/events/v3/event-definitions/purchase/?includeProperties=true": EVENT_DEFINITION_RESPONSE,
            "https://api.hubapi.com/events/v3/event-definitions/purchase/property": {"status": 200, "body": {}},
        }

        self.run_function(
            inputs=self._inputs(include_all_properties=True, event="purchase"),
            globals={
                "event": {
                    "properties": {
                        "price": 50,
                        "currency": "USD",
                        "expressDelivery": True,
                        "location": "Planet Earth",
                        "timestamp": "2024-11-11T17:25:59.812Z",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.hubapi.com/events/v3/event-definitions/purchase/property",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "name": "expressDelivery",
                        "label": "expressDelivery",
                        "type": "enumeration",
                        "description": "expressDelivery - (created by PostHog)",
                        "options": [
                            {"label": "true", "value": True, "hidden": False, "description": "True", "displayOrder": 1},
                            {
                                "label": "false",
                                "value": False,
                                "hidden": False,
                                "description": "False",
                                "displayOrder": 2,
                            },
                        ],
                    },
                },
            )
        )

        assert self.get_mock_fetch_calls()[2] == snapshot(
            (
                "https://api.hubapi.com/events/v3/event-definitions/purchase/property",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "name": "location",
                        "label": "location",
                        "type": "string",
                        "description": "location - (created by PostHog)",
                    },
                },
            )
        )

        assert self.get_mock_fetch_calls()[3] == snapshot(
            (
                "https://api.hubapi.com/events/v3/event-definitions/purchase/property",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "name": "timestamp",
                        "label": "timestamp",
                        "type": "datetime",
                        "description": "timestamp - (created by PostHog)",
                    },
                },
            )
        )

        assert self.get_mock_fetch_calls()[4] == snapshot(
            (
                "https://api.hubapi.com/events/v3/send",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "eventName": "pe_purchase",
                        "email": "example@posthog.com",
                        "occurredAt": "2024-01-01T00:00:00Z",
                        "properties": {
                            "price": 50,
                            "currency": "USD",
                            "expressDelivery": True,
                            "location": "Planet Earth",
                            "timestamp": "2024-11-11T17:25:59.812Z",
                        },
                    },
                },
            )
        )

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Not sending event.",)]

    def test_requires_correct_property_types(self):
        self.fetch_responses = {
            "https://api.hubapi.com/events/v3/event-definitions/purchase/?includeProperties=true": EVENT_DEFINITION_RESPONSE,
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(
                inputs=self._inputs(include_all_properties=True, event="purchase"),
                globals={
                    "event": {
                        "properties": {"price": "50 coins"},
                    },
                },
            )

        assert len(self.get_mock_fetch_calls()) == snapshot(1)
        assert (
            e.value.message
            == "Property type mismatch for the following properties: [{'key': 'price', 'value': '50 coins'}]. Not sending event."
        )

    def test_allowed_event_names(self):
        for event_name, formatted_name in [
            ("$identify", "identify"),
            ("$pageview", "pageview"),
            ("sign up", "sign_up"),
            ("purchase", "purchase"),
            ("6month_subscribed", None),
            ("event-name", "event-name"),
            ("subscribed_6-months", "subscribed_6-months"),
            ("custom", "custom"),
        ]:
            if formatted_name:
                self.run_function(
                    inputs=self._inputs(eventName=event_name),
                    globals={
                        "event": {
                            "properties": {"url": "https://example.com", "$browser": "Chrome"},
                        },
                    },
                )
                assert (
                    self.get_mock_fetch_calls()[0][0]
                    == f"https://api.hubapi.com/events/v3/event-definitions/{formatted_name}/?includeProperties=true"
                )
            else:
                with pytest.raises(UncaughtHogVMException) as e:
                    self.run_function(
                        inputs=self._inputs(eventName=event_name),
                        globals={
                            "event": {
                                "event": event_name,
                                "properties": {"url": "https://example.com", "$browser": "Chrome"},
                            },
                        },
                    )
                assert (
                    e.value.message
                    == f"Event name must start with a letter and can only contain lowercase letters, numbers, underscores, and hyphens. Not sending event..."
                )


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "hubspotAccessToken": "toky",
            "triggeringEvents": "$identify,$set",
            "additionalPropertyMappings": "a:b",
            "ignoredEmails": "gmail.com",
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_default_config(self):
        obj = self.get_plugin_config({})
        template = TemplateHubspotMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "access_token": {"value": "toky"},
                "email": {"value": "{person.properties.email}"},
                "properties": {
                    "value": {
                        "firstname": "{person.properties.firstname ?? person.properties.firstName ?? person.properties.first_name}",
                        "lastname": "{person.properties.lastname ?? person.properties.lastName ?? person.properties.last_name}",
                        "company": "{person.properties.company ?? person.properties.companyName ?? person.properties.company_name}",
                        "phone": "{person.properties.phone ?? person.properties.phoneNumber ?? person.properties.phone_number}",
                        "website": "{person.properties.website ?? person.properties.companyWebsite ?? person.properties.company_website}",
                        "b": "{person.properties.a}",
                    }
                },
            }
        )
        assert template["filters"] == {
            "properties": [{"key": "email", "value": "gmail.com", "operator": "not_icontains", "type": "person"}],
            "events": [
                {"id": "$identify", "name": "$identify", "type": "events", "properties": []},
                {"id": "$set", "name": "$set", "type": "events", "properties": []},
            ],
        }
        assert template["inputs_schema"][0]["key"] == "access_token"
        assert template["inputs_schema"][0]["type"] == "string"
        assert template["inputs_schema"][0]["secret"]
        assert "inputs.oauth.access_token" not in template["hog"]
        assert "inputs.access_token" in template["hog"]
