import pytest

from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.intercom.template_intercom import (
    template as template_intercom,
    template_send_event as template_intercom_event,
)

from common.hogvm.python.utils import UncaughtHogVMException


class TestTemplateIntercom(BaseHogFunctionTemplateTest):
    template = template_intercom

    def create_inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "ACCESS_TOKEN",
                "app.region": "US",
            },
            "email": "max@posthog.com",
            "include_all_properties": False,
            "properties": {
                "name": "Max AI",
                "phone": "+1234567890",
                "last_seen_at": "1234567890",
            },
            "customProperties": {},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda url, options: {  # type: ignore
            "status": 200,
            "body": {"total_count": 0},
        }

        self.run_function(
            inputs=self.create_inputs(),
            globals={
                "person": {"properties": {"$geoip_country_name": "United States", "plan": "pay-as-you-go"}},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.intercom.io/contacts/search",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {"query": {"field": "email", "operator": "=", "value": "max@posthog.com"}},
                },
            )
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.intercom.io/contacts",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "custom_attributes": {},
                        "name": "Max AI",
                        "phone": "+1234567890",
                        "last_seen_at": "1234567890",
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.mock_fetch_response = lambda url, options: {  # type: ignore
            "status": 200,
            "body": {"total_count": 1, "data": [{"id": "123"}]},
        }

        self.run_function(
            inputs=self.create_inputs(
                include_all_properties=False, customProperties={"custom_property": "custom_value"}
            ),
            globals={
                "person": {"properties": {"plan": "pay-as-you-go", "company": "PostHog"}},
            },
        )

        res = self.get_mock_fetch_calls()[1]
        res[1]["body"]["last_seen_at"] = "1234567890"

        assert res == snapshot(
            (
                "https://api.intercom.io/contacts/123",
                {
                    "method": "PUT",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "custom_attributes": {
                            "custom_property": "custom_value",
                        },
                        "name": "Max AI",
                        "phone": "+1234567890",
                        "last_seen_at": "1234567890",
                    },
                },
            )
        )

        self.run_function(
            inputs=self.create_inputs(include_all_properties=True),
            globals={
                "person": {"properties": {"plan": "pay-as-you-go", "company": "PostHog"}},
            },
        )

        res = self.get_mock_fetch_calls()[1]
        res[1]["body"]["last_seen_at"] = "1234567890"

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.intercom.io/contacts/123",
                {
                    "method": "PUT",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "custom_attributes": {},
                        "name": "Max AI",
                        "phone": "+1234567890",
                        "last_seen_at": "1234567890",
                        "plan": "pay-as-you-go",
                        "company": "PostHog",
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=self.create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])

    def test_function_errors_on_bad_status(self):
        self.fetch_responses = {
            "https://api.intercom.io/contacts/search": {
                "status": 200,
                "body": {"total_count": 0},
            },
            "https://api.intercom.io/contacts": {
                "status": 400,
                "body": {"error": "error"},
            },
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from intercom api (status 400): {'error': 'error'}"

        self.fetch_responses = {
            "https://api.intercom.io/contacts/search": {
                "status": 400,
                "body": {"error": "error"},
            },
            "https://api.intercom.io/contacts": {
                "status": 200,
                "body": {"ok": True},
            },
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from intercom api (status 400): {'error': 'error'}"

    def test_function_errors_on_multiple_contacts(self):
        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 200,
            "body": {"total_count": 2},
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Found multiple contacts with the same email address. Skipping..."


class TestTemplateIntercomEvent(BaseHogFunctionTemplateTest):
    template = template_intercom_event

    def create_inputs(self, **kwargs):
        inputs = {
            "oauth": {
                "access_token": "ACCESS_TOKEN",
                "app.region": "US",
            },
            "email": "max@posthog.com",
            "eventName": "purchase",
            "eventTime": "1234567890",
            "include_all_properties": False,
            "properties": {
                "revenue": "50",
                "currency": "USD",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.fetch_responses = {
            "https://api.intercom.io/contacts/search": {
                "status": 200,
                "body": {"total_count": 1, "data": [{"id": "123"}]},
            },
            "https://api.intercom.io/events": {"status": 200, "body": {"ok": True}},
        }

        self.run_function(
            inputs=self.create_inputs(),
            globals={
                "event": {
                    "event": "purchase",
                    "timestamp": "1234567890",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.intercom.io/contacts/search",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {"query": {"field": "email", "operator": "=", "value": "max@posthog.com"}},
                },
            )
        )

        res = self.get_mock_fetch_calls()[1]
        res[1]["body"]["created_at"] = "1234567890"
        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.intercom.io/events",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "event_name": "purchase",
                        "created_at": "1234567890",
                        "email": "max@posthog.com",
                        "metadata": {"revenue": "50", "currency": "USD"},
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.mock_fetch_response = lambda url, options: {  # type: ignore
            "status": 200,
            "body": {"total_count": 1, "data": [{"id": "123"}]},
        }

        self.run_function(
            inputs=self.create_inputs(include_all_properties=False),
            globals={
                "event": {
                    "event": "purchase",
                    "properties": {"customerType": "B2C"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.intercom.io/events",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "event_name": "purchase",
                        "created_at": "1234567890",
                        "email": "max@posthog.com",
                        "metadata": {"revenue": "50", "currency": "USD"},
                    },
                },
            )
        )

        self.run_function(
            inputs=self.create_inputs(include_all_properties=True),
            globals={
                "event": {
                    "event": "purchase",
                    "properties": {"customerType": "B2C"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.intercom.io/events",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Intercom-Version": "2.11",
                        "Accept": "application/json",
                        "Authorization": "Bearer ACCESS_TOKEN",
                    },
                    "body": {
                        "event_name": "purchase",
                        "created_at": "1234567890",
                        "email": "max@posthog.com",
                        "metadata": {
                            "revenue": "50",
                            "currency": "USD",
                            "customerType": "B2C",
                        },
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=self.create_inputs(email=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])

    def test_function_errors_on_bad_status(self):
        self.fetch_responses = {
            "https://api.intercom.io/contacts/search": {
                "status": 200,
                "body": {"total_count": 1, "data": [{"id": "123"}]},
            },
            "https://api.intercom.io/events": {
                "status": 400,
                "body": {"error": "error"},
            },
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from intercom api (status 400): {'error': 'error'}"

        self.fetch_responses = {
            "https://api.intercom.io/contacts/search": {
                "status": 400,
                "body": {"error": "error"},
            },
            "https://api.intercom.io/events": {
                "status": 200,
                "body": {"ok": True},
            },
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from intercom api (status 400): {'error': 'error'}"

    def test_function_errors_on_no_unique_contact(self):
        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 200,
            "body": {"total_count": 0},
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "No unique contact found. Skipping..."

        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 200,
            "body": {"total_count": 2},
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "No unique contact found. Skipping..."
