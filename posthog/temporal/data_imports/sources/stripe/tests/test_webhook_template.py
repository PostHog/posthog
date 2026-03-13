import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.temporal.data_imports.sources.stripe.webhook_template import template


class TestStripeWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data: dict = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {},
                "query": {},
                "stringBody": "",
                "ip": "127.0.0.1",
            },
        }
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _make_signed_request(self, secret: str, body: dict | None = None, method: str = "POST") -> dict:
        payload = json.dumps(body or {"type": "invoice.payment_succeeded", "data": {"object": {"id": "inv_1"}}})
        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.{payload}"
        signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {"stripe-signature": f"t={timestamp},v1={signature}"},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def test_valid_signed_webhook(self):
        secret = "whsec_test"
        globals = self._make_signed_request(secret)
        res = self.run_function({"signing_secret": secret, "bypass_signature_check": False}, globals=globals)
        assert res.result == globals["request"]["body"]

    def test_non_post_request_returns_405(self):
        globals = self._make_signed_request("whsec_test", method="GET")
        res = self.run_function({"signing_secret": "whsec_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_missing_signature_returns_400(self):
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {"type": "test"},
                "stringBody": '{"type": "test"}',
                "query": {},
            }
        }
        res = self.run_function({"signing_secret": "whsec_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}

    def test_invalid_signature_returns_400(self):
        globals = self._make_signed_request("wrong_secret")
        res = self.run_function({"signing_secret": "correct_secret", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}

    def test_bypass_signature_check(self):
        body = {"type": "charge.succeeded", "data": {"object": {"id": "ch_1"}}}
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }
        res = self.run_function({"signing_secret": "", "bypass_signature_check": True}, globals=globals)
        assert res.result == body

    @parameterized.expand(
        [
            ("no_parts", "garbage"),
            ("missing_v1", "t=12345"),
            ("missing_timestamp", "v1=abcdef"),
        ]
    )
    def test_unparseable_signature_returns_400(self, _name, sig_value):
        globals = {
            "request": {
                "method": "POST",
                "headers": {"stripe-signature": sig_value},
                "body": {"type": "test"},
                "stringBody": '{"type": "test"}',
                "query": {},
            }
        }
        res = self.run_function({"signing_secret": "whsec_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Could not parse signature"}}
