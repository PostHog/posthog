from typing import Optional

from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.mailgun.template_mailgun import template_mailgun_send_email


def create_inputs(overrides: Optional[dict] = None):
    inputs = {
        "domain_name": "DOMAIN_NAME",
        "api_key": "API_KEY",
        "host": "api.mailgun.net",
        "template": {
            "to": "example@posthog.com",
            "from": "noreply@posthog.com",
            "subject": "TEST SUBJECT",
            "html": "<h1>Test</h1>",
            "text": "Test",
        },
    }
    if overrides:
        inputs.update(overrides)
    return inputs


class TestTemplateMailgunSendEmail(BaseHogFunctionTemplateTest):
    template = template_mailgun_send_email

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(), functions={"generateUUIDv4": lambda: "bcf493bf-5640-4519-817e-610dc1ba48bd"}
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.mailgun.net/v3/DOMAIN_NAME/messages",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic YXBpOkFQSV9LRVk=",
                        "Content-Type": "multipart/form-data; boundary=---011000010111000001101001",
                    },
                    "body": """\
-----011000010111000001101001\r
Content-Disposition: form-data; name="from"\r
\r
noreply@posthog.com\r
-----011000010111000001101001\r
Content-Disposition: form-data; name="to"\r
\r
example@posthog.com\r
-----011000010111000001101001\r
Content-Disposition: form-data; name="subject"\r
\r
TEST SUBJECT\r
-----011000010111000001101001\r
Content-Disposition: form-data; name="text"\r
\r
Test\r
-----011000010111000001101001\r
Content-Disposition: form-data; name="html"\r
\r
<h1>Test</h1>\r
-----011000010111000001101001\r
""",
                },
            )
        )

        assert self.get_mock_print_calls() == []

    def test_function_ignores_no_email(self):
        self.run_function(inputs=create_inputs({"template": {"to": ""}}))

        assert self.get_mock_fetch_calls() == []
