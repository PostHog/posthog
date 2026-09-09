import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.salesforce.template_salesforce import (
    TemplatSalesforceMigrator,
    template_create as template_salesforce_create,
    template_lookup as template_salesforce_lookup,
    template_update as template_salesforce_update,
)

from products.cdp.backend.models.plugin import PluginConfig

from common.hogvm.python.utils import UncaughtHogVMException


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

    def test_rejects_path_with_empty_segment(self):
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(path="Contact/Email/"))
        assert "is missing a value" in str(e.value)
        assert self.get_mock_fetch_calls() == []

    def test_returns_response_body(self):
        self.mock_fetch_response = lambda *args: {"status": 201, "body": {"id": "0031", "success": True}}  # type: ignore
        assert self.run_function(self._inputs()).result == {"id": "0031", "success": True}


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

    @parameterized.expand(
        [
            ("empty external id value", "Lead/Email/"),
            ("trailing slash", "Lead/"),
            ("empty path", ""),
        ]
    )
    def test_rejects_path_with_empty_segment(self, _name: str, path: str):
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(path=path))
        assert "is missing a value" in str(e.value)
        assert self.get_mock_fetch_calls() == []

    def test_rejects_bare_object_name(self):
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(path="Lead"))
        assert "has no record identifier" in str(e.value)
        assert self.get_mock_fetch_calls() == []

    def test_returns_response_body(self):
        self.mock_fetch_response = lambda *args: {"status": 201, "body": {"id": "00Q1", "created": True}}  # type: ignore
        assert self.run_function(self._inputs()).result == {"id": "00Q1", "created": True}

    @parameterized.expand([("no content", 204, None), ("empty body", 200, {})])
    def test_reports_success_when_salesforce_returns_no_body(self, _name: str, status: int, body: dict | None):
        self.mock_fetch_response = lambda *args: {"status": status, "body": body}  # type: ignore
        assert self.run_function(self._inputs(path="Lead/00Q1")).result == {"success": True}


class TestTemplateSalesforceLookup(BaseHogFunctionTemplateTest):
    template = template_salesforce_lookup

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "instance_url": "https://example.my.salesforce.com",
                "access_token": "oauth-1234",
            },
            "object": "Lead",
            "match_field": "Email",
            "match_value": "example@posthog.com",
            "fields": "Id",
        }
        inputs.update(kwargs)
        return inputs

    def _respond(self, records):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"records": records}}  # type: ignore

    def _query(self):
        return self.get_mock_fetch_calls()[0][0].split("?q=")[1]

    def test_queries_salesforce_and_returns_the_match(self):
        self._respond([{"Id": "00Q1", "Status": "Open"}])
        result = self.run_function(self._inputs(fields="Id, Status")).result
        url, options = self.get_mock_fetch_calls()[0]
        assert url == (
            "https://example.my.salesforce.com/services/data/v61.0/query/"
            "?q=SELECT%20Id%2C%20Status%20FROM%20Lead%20WHERE%20Email%20%3D%20%27example@posthog.com%27%20LIMIT%202"
        )
        assert options["method"] == "GET"
        assert result == {
            "found": True,
            "multiple": False,
            "id": "00Q1",
            "record": {"Id": "00Q1", "Status": "Open"},
        }

    @parameterized.expand(
        [
            ("single quote", "x' OR Name != '", "%27x%5C%27%20OR%20Name%20!%3D%20%5C%27%27"),
            ("plus addressing", "a+b@posthog.com", "%27a%2Bb@posthog.com%27"),
            ("backslash", "a\\b@posthog.com", "%27a%5C%5Cb@posthog.com%27"),
            ("embedded newline", "a@\nb.com", "%27a@%5Cnb.com%27"),
        ]
    )
    def test_escapes_the_match_value(self, _name: str, match_value: str, expected: str):
        self._respond([])
        self.run_function(self._inputs(match_value=match_value))
        assert expected in self._query()

    def test_returns_not_found_instead_of_failing(self):
        self._respond([])
        assert self.run_function(self._inputs()).result == {
            "found": False,
            "multiple": False,
            "id": None,
            "record": None,
        }

    def test_flags_more_than_one_match(self):
        self._respond([{"Id": "00Q1"}, {"Id": "00Q2"}])
        result = self.run_function(self._inputs()).result
        assert result["multiple"] is True
        assert result["id"] == "00Q1"

    def test_rejects_empty_match_value(self):
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(match_value=""))
        assert "no value to match on" in str(e.value)
        assert self.get_mock_fetch_calls() == []

    @parameterized.expand(
        [
            ("object", {"object": "Lead WHERE Id != null"}),
            ("match field", {"match_field": "Email'"}),
            ("returned field", {"fields": "Id, Name FROM User"}),
        ]
    )
    def test_rejects_invalid_api_names(self, _name: str, override: dict):
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(**override))
        assert "is not a valid Salesforce API name" in str(e.value)
        assert self.get_mock_fetch_calls() == []


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
