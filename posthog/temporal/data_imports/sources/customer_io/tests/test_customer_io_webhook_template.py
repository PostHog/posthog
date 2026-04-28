import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.temporal.data_imports.sources.customer_io.webhook_template import template

SOURCE_ID = "source_test_123"


class TestCustomerIOWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _make_signed_request(
        self,
        secret: str,
        body: dict | None = None,
        method: str = "POST",
        timestamp: int | None = None,
    ) -> dict:
        payload = json.dumps(
            body
            or {
                "object_type": "email",
                "event_id": "01E2EMRMM6TZ12ZNQDWQ12",
                "timestamp": 1699999999,
                "metric": "delivered",
            }
        )
        ts_str = str(timestamp if timestamp is not None else int(time.time()))
        signed_payload = f"v0:{ts_str}:{payload}"
        signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {"x-cio-signature": signature, "x-cio-timestamp": ts_str},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def test_valid_signed_webhook(self):
        secret = "cio_signing_key_test"
        globals = self._make_signed_request(secret)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"email": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_abc")

    def test_non_post_request_returns_405(self):
        globals = self._make_signed_request("cio_signing_key_test", method="GET")
        res = self.run_function(
            {
                "signing_secret": "cio_signing_key_test",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_invalid_signature_returns_400(self):
        globals = self._make_signed_request("wrong_secret")
        res = self.run_function(
            {
                "signing_secret": "correct_secret",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}

    def test_stale_timestamp_returns_400(self):
        secret = "cio_signing_key_test"
        stale_ts = int(time.time()) - 400  # 400s > 300s tolerance
        globals = self._make_signed_request(secret, timestamp=stale_ts)
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"email": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Timestamp outside tolerance"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_bypass_signature_check(self):
        body = {"object_type": "push", "event_id": "evt_1", "metric": "clicked"}
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }
        self.run_function(
            {
                "signing_secret": "",
                "bypass_signature_check": True,
                "schema_mapping": {"push": "schema_push"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_push")

    def test_missing_object_type_returns_200_and_skips(self):
        secret = "cio_signing_key_test"
        globals = self._make_signed_request(secret, body={"event_id": "evt_no_type", "metric": "whatever"})
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"email": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 200, "body": "No object type found, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_unmapped_object_type_returns_200_and_skips(self):
        secret = "cio_signing_key_test"
        globals = self._make_signed_request(secret, body={"object_type": "webhook", "event_id": "evt_2"})
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"email": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {
            "httpResponse": {"status": 200, "body": "No schema mapping for object type: webhook, skipping"}
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("null", None),
            ("empty_string", ""),
        ]
    )
    def test_missing_signing_secret_returns_400(self, _name, signing_secret):
        globals = {
            "request": {
                "method": "POST",
                "headers": {"x-cio-signature": "abc", "x-cio-timestamp": "123"},
                "body": {"object_type": "email"},
                "stringBody": '{"object_type": "email"}',
                "query": {},
            }
        }
        res = self.run_function(
            {
                "signing_secret": signing_secret,
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}

    @parameterized.expand(
        [
            ("missing_both", {}),
            ("missing_signature", {"x-cio-timestamp": "12345"}),
            ("missing_timestamp", {"x-cio-signature": "abcdef"}),
        ]
    )
    def test_missing_signature_headers_returns_400(self, _name, headers):
        globals = {
            "request": {
                "method": "POST",
                "headers": headers,
                "body": {"object_type": "email"},
                "stringBody": '{"object_type": "email"}',
                "query": {},
            }
        }
        res = self.run_function(
            {
                "signing_secret": "cio_signing_key_test",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}
