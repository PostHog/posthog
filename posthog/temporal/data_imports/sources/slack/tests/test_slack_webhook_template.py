import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.temporal.data_imports.sources.slack.webhook_template import template


class TestSlackWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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
        timestamp: str | None = None,
    ) -> dict:
        payload = json.dumps(
            body
            or {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel": "C123",
                    "ts": "1700000000.000001",
                    "text": "hello",
                },
            }
        )
        ts = timestamp or str(int(time.time()))
        sig_basestring = f"v0:{ts}:{payload}"
        signature = "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {
                    "x-slack-signature": signature,
                    "x-slack-request-timestamp": ts,
                },
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def test_valid_signed_event_callback(self):
        secret = "slack_signing_secret"
        globals = self._make_signed_request(secret)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"C123": "schema_abc"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_abc")

    def test_url_verification_challenge_is_echoed(self):
        secret = "slack_signing_secret"
        body = {"type": "url_verification", "challenge": "chal_xyz"}
        globals = self._make_signed_request(secret, body=body)
        res = self.run_function(
            {"signing_secret": secret, "bypass_signature_check": False, "schema_mapping": {}},
            globals=globals,
        )
        assert res.result == {
            "httpResponse": {
                "status": 200,
                "contentType": "application/json",
                "body": json.dumps({"challenge": "chal_xyz"}),
            }
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self):
        globals = self._make_signed_request("slack_signing_secret", method="GET")
        res = self.run_function(
            {"signing_secret": "slack_signing_secret", "bypass_signature_check": False},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

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
                "headers": {},
                "body": {"type": "event_callback"},
                "stringBody": '{"type": "event_callback"}',
                "query": {},
            }
        }
        res = self.run_function(
            {"signing_secret": signing_secret, "bypass_signature_check": False},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}

    def test_missing_signature_headers_returns_400(self):
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {"type": "event_callback"},
                "stringBody": '{"type": "event_callback"}',
                "query": {},
            }
        }
        res = self.run_function(
            {"signing_secret": "slack_signing_secret", "bypass_signature_check": False},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature headers"}}

    def test_invalid_signature_returns_400(self):
        globals = self._make_signed_request("wrong_secret")
        res = self.run_function(
            {"signing_secret": "correct_secret", "bypass_signature_check": False},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}

    @parameterized.expand(
        [
            ("timestamp_too_old", lambda: str(int(time.time()) - 600)),
            ("timestamp_too_new", lambda: str(int(time.time()) + 600)),
        ]
    )
    def test_stale_timestamp_returns_400(self, _name, ts_factory):
        secret = "slack_signing_secret"
        globals = self._make_signed_request(secret, timestamp=ts_factory())
        res = self.run_function(
            {"signing_secret": secret, "bypass_signature_check": False, "schema_mapping": {}},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Stale request timestamp"}}

    def test_bypass_signature_check(self):
        body = {
            "type": "event_callback",
            "event": {"type": "message", "channel": "C999", "ts": "1700000500.000001"},
        }
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
                "schema_mapping": {"C999": "schema_999"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_999")

    def test_non_event_callback_type_is_skipped(self):
        secret = "slack_signing_secret"
        body = {"type": "something_else", "event": {"channel": "C1"}}
        globals = self._make_signed_request(secret, body=body)
        res = self.run_function(
            {"signing_secret": secret, "bypass_signature_check": False, "schema_mapping": {"C1": "s_1"}},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 200, "body": "Not an event_callback, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_missing_channel_in_event_is_skipped(self):
        secret = "slack_signing_secret"
        body = {"type": "event_callback", "event": {"type": "message", "ts": "1700000000.000001"}}
        globals = self._make_signed_request(secret, body=body)
        res = self.run_function(
            {"signing_secret": secret, "bypass_signature_check": False, "schema_mapping": {}},
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 200, "body": "No channel found in event, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_unmapped_channel_is_skipped(self):
        secret = "slack_signing_secret"
        globals = self._make_signed_request(secret)
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"C_OTHER": "schema_other"},
            },
            globals=globals,
        )
        assert res.result == {
            "httpResponse": {
                "status": 200,
                "body": "No schema mapping for channel: C123, skipping",
            }
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
