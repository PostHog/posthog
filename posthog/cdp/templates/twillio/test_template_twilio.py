import pytest
from common.hogvm.python.utils import UncaughtHogVMException
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.twillio.template_twilio import template as template_twilio
from inline_snapshot import snapshot


class TestTemplateTwilio(BaseHogFunctionTemplateTest):
    template = template_twilio

    def _inputs(self, **kwargs):
        inputs = {
            "accountSid": "AC123456",
            "authToken": "auth_token_123",
            "fromPhoneNumber": "+12292109687",
            "phoneNumber": "+491633950489",
            "smsBody": "Test message",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200}  # type: ignore
        res = self.run_function(self._inputs())

        assert res.result is None

        # Verify the fetch call was made with correct parameters
        fetch_calls = self.get_mock_fetch_calls()
        assert len(fetch_calls) == 1
        url, options = fetch_calls[0]

        assert url == "https://api.twilio.com/2010-04-01/Accounts/AC123456/Messages.json"
        assert options["method"] == "POST"
        assert options["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert options["headers"]["Authorization"].startswith("Basic ")

        assert self.get_mock_print_calls() == snapshot([("SMS sent successfully via Twilio!",)])

    def test_function_throws_error_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400}  # type: ignore

        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs())

        assert "Error sending SMS" in str(e.value.message)

    def test_function_with_custom_message(self):
        self.mock_fetch_response = lambda *args: {"status": 200}  # type: ignore

        custom_inputs = self._inputs(smsBody="Custom notification: {event.event}")
        res = self.run_function(custom_inputs)

        assert res.result is None
        fetch_calls = self.get_mock_fetch_calls()
        assert len(fetch_calls) == 1

        # Verify custom message is included in the body
        url, options = fetch_calls[0]
        assert "Custom%20notification" in options["body"]

    def test_function_with_invalid_phone_number(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"message": "Invalid phone number"}}  # type: ignore

        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(self._inputs(phoneNumber="invalid"))

        assert "Error sending SMS" in str(e.value.message)
