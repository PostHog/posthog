import pytest

from products.cdp.backend.templates.helpers import BaseHogFunctionTemplateTest
from products.cdp.backend.templates.knock2.template_knock2 import template as template_knock2

from common.hogvm.python.utils import UncaughtHogVMException


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "k2_apikey12345",
        "projectToken": "phc_token12345",
        "distinctId": "user-42",
        "email": "max@posthog.com",
        "name": "Max",
        "personId": "0190a1b2-c3d4-7e8f-9012-3456789abcde",
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateKnock2(BaseHogFunctionTemplateTest):
    template = template_knock2

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"data": {"status": "recorded"}}}  # type: ignore
        self.run_function(inputs=create_inputs())
        assert self.get_mock_fetch_calls()[0] == (
            "https://api.knock2.ai/v1/posthog/identify",
            {
                "body": {
                    "distinct_id": "user-42",
                    "token": "phc_token12345",
                    "email": "max@posthog.com",
                    "name": "Max",
                    "person_id": "0190a1b2-c3d4-7e8f-9012-3456789abcde",
                },
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer k2_apikey12345",
                    "Content-Type": "application/json",
                },
            },
        )

    def test_function_requires_distinct_id(self):
        self.run_function(inputs=create_inputs(distinctId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("No distinct ID set. Skipping...",)]

    def test_function_skips_a_person_with_no_email_and_no_name(self):
        self.run_function(inputs=create_inputs(email="", name=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("No email or name on this person. Skipping...",)]

    def test_function_sends_a_person_with_only_a_name(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"data": {"status": "recorded"}}}  # type: ignore
        self.run_function(inputs=create_inputs(email=""))

        assert self.get_mock_fetch_calls()[0][1]["body"]["name"] == "Max"

    def test_function_raises_on_error(self):
        self.mock_fetch_response = lambda *args: {"status": 401, "body": {"error": "unauthorized"}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=create_inputs())
        assert e.value.message == "Error from api.knock2.ai (status 401): {'error': 'unauthorized'}"
