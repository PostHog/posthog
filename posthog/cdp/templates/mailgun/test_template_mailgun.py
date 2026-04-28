from typing import Optional

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

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.mailgun.net/v3/DOMAIN_NAME/messages",
            {
                "method": "POST",
                "headers": {
                    "Authorization": "Basic YXBpOkFQSV9LRVk=",
                    "Content-Type": "multipart/form-data; boundary=---bcf493bf-5640-4519-817e-610dc1ba48bd",
                },
                "body": """\
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
Content-Disposition: form-data; name="from"\r
\r
noreply@posthog.com\r
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
Content-Disposition: form-data; name="to"\r
\r
example@posthog.com\r
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
Content-Disposition: form-data; name="subject"\r
\r
TEST SUBJECT\r
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
Content-Disposition: form-data; name="text"\r
\r
Test\r
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
Content-Disposition: form-data; name="html"\r
\r
<h1>Test</h1>\r
-----bcf493bf-5640-4519-817e-610dc1ba48bd\r
""",
            },
        )

        assert self.get_mock_print_calls() == []

    def test_function_prevents_boundary_injection(self):
        # The fix relies on boundary unpredictability — an attacker who doesn't know
        # the random UUID can't craft a payload that splits the multipart form.
        # We use the old hardcoded boundary as the attacker's guess to simulate this.
        malicious_to = (
            "victim@example.com\r\n"
            "-----011000010111000001101001\r\n"
            'Content-Disposition: form-data; name="bcc"\r\n'
            "\r\n"
            "attacker@evil.com"
        )
        inputs = create_inputs()
        inputs["template"]["to"] = malicious_to
        self.run_function(
            inputs=inputs,
            functions={"generateUUIDv4": lambda: "bcf493bf-5640-4519-817e-610dc1ba48bd"},
        )

        fetch_calls = self.get_mock_fetch_calls()
        assert len(fetch_calls) == 1
        body = fetch_calls[0][1]["body"]
        boundary = fetch_calls[0][1]["headers"]["Content-Type"].split("boundary=")[1]
        # Split body by the actual boundary — "bcc" must not be a real form field
        parts = body.split(f"--{boundary}")
        field_names = []
        for part in parts:
            if 'Content-Disposition: form-data; name="' in part:
                name = part.split('name="')[1].split('"')[0]
                field_names.append(name)
        assert "bcc" not in field_names, f"Injected 'bcc' field found as separate form part: {field_names}"

    def test_function_ignores_no_email(self):
        self.run_function(inputs=create_inputs({"template": {"to": ""}}))

        assert self.get_mock_fetch_calls() == []
