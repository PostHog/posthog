import pytest

from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.klaviyo.template_klaviyo import (
    template_event as klaviyo_event,
    template_user as klaviyo_user,
)

from common.hogvm.python.utils import UncaughtHogVMException


class TestTemplateKlaviyoUser(BaseHogFunctionTemplateTest):
    template = klaviyo_user

    def create_inputs(self, **kwargs):
        inputs = {
            "apiKey": "API_KEY",
            "email": "max@posthog.com",
            "externalId": "EXTERNAL_ID",
            "include_all_properties": False,
            "customProperties": {
                "first_name": "Max",
                "last_name": "AI",
                "title": "Hedgehog in Residence",
                "organization": "PostHog",
                "phone_number": "+0123456789",
            },
        }
        inputs.update(kwargs)

        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self.create_inputs(),
            globals={
                "person": {"properties": {"$geoip_country_name": "United States", "plan": "pay-as-you-go"}},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://a.klaviyo.com/api/profiles",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Klaviyo-API-Key API_KEY",
                        "revision": "2024-10-15",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "data": {
                            "type": "profile",
                            "attributes": {
                                "location": {"country": "United States"},
                                "properties": {
                                    "first_name": "Max",
                                    "last_name": "AI",
                                    "title": "Hedgehog in Residence",
                                    "organization": "PostHog",
                                    "phone_number": "+0123456789",
                                },
                                "email": "max@posthog.com",
                                "external_id": "EXTERNAL_ID",
                            },
                        }
                    },
                },
            )
        )

    def test_patch_existing_profile(self):
        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 409,
            "body": {
                "errors": [
                    {
                        "id": "207e2b13-ac84-4afe-a064-616a33006e6e",
                        "status": 409,
                        "code": "duplicate_profile",
                        "title": "Conflict.",
                        "detail": "A profile already exists with one of these identifiers.",
                        "source": {"pointer": "/data/attributes"},
                        "links": {},
                        "meta": {"duplicate_profile_id": "01JAFS0VVWGJFE7QE4EJQBA5AS"},
                    }
                ]
            },
        }

        # both requests will fail with error code 409
        with pytest.raises(UncaughtHogVMException):
            self.run_function(inputs=self.create_inputs())

        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://a.klaviyo.com/api/profiles/01JAFS0VVWGJFE7QE4EJQBA5AS",
                {
                    "method": "PATCH",
                    "headers": {
                        "Authorization": "Klaviyo-API-Key API_KEY",
                        "revision": "2024-10-15",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "data": {
                            "type": "profile",
                            "attributes": {
                                "location": {},
                                "properties": {
                                    "first_name": "Max",
                                    "last_name": "AI",
                                    "title": "Hedgehog in Residence",
                                    "organization": "PostHog",
                                    "phone_number": "+0123456789",
                                },
                                "email": "max@posthog.com",
                                "external_id": "EXTERNAL_ID",
                            },
                            "id": "01JAFS0VVWGJFE7QE4EJQBA5AS",
                        }
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=self.create_inputs(include_all_properties=False),
            globals={"person": {"properties": {"$geoip_country_name": "United States", "plan": "pay-as-you-go"}}},
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["data"]["attributes"]["properties"] == snapshot(
            {
                "first_name": "Max",
                "last_name": "AI",
                "title": "Hedgehog in Residence",
                "organization": "PostHog",
                "phone_number": "+0123456789",
            }
        )

        self.run_function(
            inputs=self.create_inputs(include_all_properties=True),
            globals={"person": {"properties": {"$geoip_country_name": "United States", "plan": "pay-as-you-go"}}},
        )
        assert self.get_mock_fetch_calls()[0][1]["body"]["data"]["attributes"]["properties"] == snapshot(
            {
                "first_name": "Max",
                "last_name": "AI",
                "title": "Hedgehog in Residence",
                "organization": "PostHog",
                "phone_number": "+0123456789",
                "plan": "pay-as-you-go",
            }
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=self.create_inputs(email=None, externalId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("Email or External ID has to be set. Skipping...",)])

    def test_function_errors_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "error"}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from a.klaviyo.com api: 400: {'error': 'error'}"


class TestTemplateKlaviyoEvent(BaseHogFunctionTemplateTest):
    def create_inputs(self, **kwargs):
        inputs = {
            "apiKey": "API_KEY",
            "email": "max@posthog.com",
            "externalId": "EXTERNAL_ID",
            "include_all_properties": False,
            "attributes": {"price": "25.99", "currency": "USD"},
        }
        inputs.update(kwargs)

        return inputs

    template = klaviyo_event

    def test_function_works(self):
        self.run_function(
            inputs=self.create_inputs(),
            globals={
                "event": {
                    "event": "purchase",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://a.klaviyo.com/api/events",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Klaviyo-API-Key API_KEY",
                        "revision": "2024-10-15",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "data": {
                            "type": "event",
                            "attributes": {
                                "properties": {"price": "25.99", "currency": "USD"},
                                "metric": {"data": {"type": "metric", "attributes": {"name": "purchase"}}},
                                "profile": {
                                    "data": {
                                        "type": "profile",
                                        "attributes": {"email": "max@posthog.com", "external_id": "EXTERNAL_ID"},
                                    }
                                },
                            },
                        }
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=self.create_inputs(include_all_properties=False),
            globals={
                "event": {"event": "purchase", "properties": {"customerType": "B2C"}},
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["data"]["attributes"]["properties"] == snapshot(
            {
                "price": "25.99",
                "currency": "USD",
            }
        )

        self.run_function(
            inputs=self.create_inputs(include_all_properties=True),
            globals={
                "event": {"event": "purchase", "properties": {"customerType": "B2C"}},
            },
        )
        assert self.get_mock_fetch_calls()[0][1]["body"]["data"]["attributes"]["properties"] == snapshot(
            {"price": "25.99", "currency": "USD", "customerType": "B2C"}
        )

    def test_function_requires_identifier(self):
        self.run_function(inputs=self.create_inputs(email=None, externalId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("Email or External ID has to be set. Skipping...",)])

    def test_function_errors_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "error"}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=self.create_inputs())
        assert e.value.message == "Error from a.klaviyo.com api: 400: {'error': 'error'}"
