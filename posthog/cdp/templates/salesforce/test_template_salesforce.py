import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.salesforce.template_salesforce import (
    TemplatSalesforceMigrator,
    template_create as template_salesforce_create,
    template_update as template_salesforce_update,
)

from products.cdp.backend.models.plugin import PluginConfig


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
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
            {
                "body": {"foo": "bar"},
                "method": "POST",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    def test_add_all_event_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_event_properties=True))
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
            {
                "body": {"$current_url": "https://example.com", "foo": "bar"},
                "method": "POST",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    def test_add_all_person_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_person_properties=True))
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Contact",
            {
                "body": {"email": "example@posthog.com", "foo": "bar"},
                "method": "POST",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    @parameterized.expand(
        [
            (
                "expired_session",
                401,
                [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}],
                "Salesforce rejected the credentials (status 401, INVALID_SESSION_ID: Session expired or invalid). Reconnect the Salesforce account for this destination.",
            ),
            (
                "missing_create_permission",
                400,
                [{"message": "entity type cannot be inserted: Form Entry", "errorCode": "INSUFFICIENT_ACCESS"}],
                "Salesforce rejected the request (status 400, INSUFFICIENT_ACCESS: entity type cannot be inserted: Form Entry). Retrying will not help. Check the object permissions, the field values, and the object path in Salesforce.",
            ),
            (
                "field_too_long",
                400,
                [{"message": "Landing_URL__c: data value too large", "errorCode": "STRING_TOO_LONG"}],
                "Salesforce rejected the request (status 400, STRING_TOO_LONG: Landing_URL__c: data value too large). Retrying will not help. Check the object permissions, the field values, and the object path in Salesforce.",
            ),
            (
                "path_points_at_collection",
                405,
                [
                    {
                        "message": "HTTP Method PATCH not allowed. Allowed are HEAD,GET,POST",
                        "errorCode": "METHOD_NOT_ALLOWED",
                    }
                ],
                "Salesforce rejected the request because the object path points at a collection, not a single record (status 405, METHOD_NOT_ALLOWED: HTTP Method PATCH not allowed. Allowed are HEAD,GET,POST). To update a record, set the object path to Object/ExternalIdField/value, for example Lead/Email/jane@example.com. Make sure the external ID field and its value are both present.",
            ),
            (
                "forbidden_without_error_code",
                403,
                "Forbidden",
                "Salesforce rejected the request (status 403, Forbidden). Retrying will not help. Check the object permissions, the field values, and the object path in Salesforce.",
            ),
            (
                "rate_limited",
                429,
                [{"message": "Too many requests", "errorCode": "REQUEST_LIMIT_EXCEEDED"}],
                "Salesforce request failed with status 429",
            ),
            (
                "server_error",
                503,
                "Service Unavailable",
                "Salesforce request failed with status 503: Service Unavailable",
            ),
        ]
    )
    def test_error_is_classified(self, _name, status, body, expected):
        self.mock_fetch_response = lambda *args: {"status": status, "body": body}  # type: ignore
        with pytest.raises(Exception) as exc:
            self.run_function(self._inputs())
        assert expected in str(exc.value)


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
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
            {
                "body": {"foo": "bar"},
                "method": "PATCH",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    def test_add_all_event_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_event_properties=True))
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
            {
                "body": {"$current_url": "https://example.com", "foo": "bar"},
                "method": "PATCH",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    def test_add_all_person_properties(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(self._inputs(include_all_person_properties=True))
        assert self.get_mock_fetch_calls()[0] == (
            "https://example.my.salesforce.com/services/data/v61.0/sobjects/Lead/Email/example@posthog.com",
            {
                "body": {"email": "example@posthog.com", "foo": "bar"},
                "method": "PATCH",
                "headers": {"Authorization": "Bearer oauth-1234", "Content-Type": "application/json"},
            },
        )

    def test_permission_error_is_not_reported_as_auth(self):
        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 400,
            "body": [{"message": "entity type cannot be inserted: Form Entry", "errorCode": "INSUFFICIENT_ACCESS"}],
        }
        with pytest.raises(Exception) as exc:
            self.run_function(self._inputs())
        assert "INSUFFICIENT_ACCESS" in str(exc.value)
        assert "credentials" not in str(exc.value)


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
        assert template["inputs"] == {
            "path": {"value": "ignored"},
            "properties": {"value": {"email": "{event.properties.email}", "$browser": "{event.properties.$browser}"}},
        }

        assert template["filters"] == {
            "events": [
                {"id": "a", "name": "a", "order": 0, "type": "events"},
                {"id": "b", "name": "b", "order": 0, "type": "events"},
            ]
        }

    def test_include_all(self):
        obj = self.get_plugin_config({"propertiesToInclude": ""})
        template = TemplatSalesforceMigrator.migrate(obj)
        assert template["inputs"] == {
            "path": {"value": "ignored"},
            "include_all_event_properties": {"value": True},
        }

        assert template["filters"] == {
            "events": [
                {"id": "a", "name": "a", "order": 0, "type": "events"},
                {"id": "b", "name": "b", "order": 0, "type": "events"},
            ]
        }
