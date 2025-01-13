import pytest
from hogvm.python.utils import UncaughtHogVMException
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.twillio.template_twilio import template as template_twilio


class TestTemplateTwilio(BaseHogFunctionTemplateTest):
    template = template_twilio

    def _inputs(self, **kwargs):
        inputs = {
            "accountSid": "AC1234567890",
            "authToken": "auth_token_123",
            "fromPhoneNumber": "+15551234567",
            "phoneNumber": "+15557654321",
            "smsBody": "Test notification",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {
            "status": 200,
            "body": {
                "account_sid": "AC1234567890",
                "status": "queued",
                "body": "Test notification - Event: test_event at 2024-01-01T12:00:00Z",
                "from": "+15551234567",
                "to": "+15557654321",
                "sid": "SM1c4944efd48afa3b47961fd5c40c8108",
                "error_code": None,
                "error_message": None,
            },
        }
        res = self.run_function(
            self._inputs(),
            event={
                "event": "test_event",
                "timestamp": "2024-01-01T12:00:00Z",
            },
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.twilio.com/2010-04-01/Accounts/AC1234567890/Messages.json",
            {
                "body": f"To=%2B15557654321&From=%2B15551234567&Body=Test+notification+-+Event:+test_event+at+2024-01-01T12:00:00Z",
                "method": "POST",
                "headers": {
                    "Authorization": "Basic QUMxMjM0NTY3ODkwOmF1dGhfdG9rZW5fMTIz",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            },
        )

        assert self.get_mock_print_calls() == ["SMS sent successfully via Twilio!"]

    def test_function_raises_on_error(self):
        self.mock_fetch_response = lambda *args: {
            "status": 400,
            "body": {"message": "Invalid phone number"},
        }
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(
                self._inputs(),
                event={
                    "event": "test_event",
                    "timestamp": "2024-01-01T12:00:00Z",
                },
            )

        assert "Error sending SMS" in str(e.value)
