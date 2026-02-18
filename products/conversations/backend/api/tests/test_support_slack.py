import hmac
import time
import hashlib

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import SlackIntegrationError

from products.conversations.backend.support_slack import validate_support_request


class TestValidateSupportRequest(SimpleTestCase):
    def _make_request(self, timestamp: str, body: str, signature: str | None = None) -> MagicMock:
        request = MagicMock()
        request.body = body.encode("utf-8")
        request.headers = {
            "X-SLACK-REQUEST-TIMESTAMP": timestamp,
            "X-SLACK-SIGNATURE": signature or "",
        }
        return request

    def _compute_signature(self, secret: str, timestamp: str, body: str) -> str:
        sig_basestring = f"v0:{timestamp}:{body}"
        return (
            "v0="
            + hmac.new(
                secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
        )

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_valid_signature_passes(self, mock_settings: MagicMock) -> None:
        secret = "test-secret"
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": secret}

        timestamp = str(int(time.time()))
        body = '{"type": "event_callback"}'
        signature = self._compute_signature(secret, timestamp, body)

        request = self._make_request(timestamp, body, signature)

        validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_invalid_signature_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": "test-secret"}

        request = self._make_request(str(int(time.time())), "{}", "v0=invalid")

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_missing_signature_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": "test-secret"}

        request = MagicMock()
        request.body = b"{}"
        request.headers = {"X-SLACK-REQUEST-TIMESTAMP": str(int(time.time()))}

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_missing_timestamp_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": "test-secret"}

        request = MagicMock()
        request.body = b"{}"
        request.headers = {"X-SLACK-SIGNATURE": "v0=something"}

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_expired_timestamp_raises(self, mock_settings: MagicMock) -> None:
        secret = "test-secret"
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": secret}

        old_timestamp = str(int(time.time()) - 400)
        body = "{}"
        signature = self._compute_signature(secret, old_timestamp, body)

        request = self._make_request(old_timestamp, body, signature)

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_future_timestamp_beyond_tolerance_raises(self, mock_settings: MagicMock) -> None:
        secret = "test-secret"
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": secret}

        future_timestamp = str(int(time.time()) + 120)
        body = "{}"
        signature = self._compute_signature(secret, future_timestamp, body)

        request = self._make_request(future_timestamp, body, signature)

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)

    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_future_timestamp_within_tolerance_passes(self, mock_settings: MagicMock) -> None:
        secret = "test-secret"
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": secret}

        future_timestamp = str(int(time.time()) + 30)
        body = "{}"
        signature = self._compute_signature(secret, future_timestamp, body)

        request = self._make_request(future_timestamp, body, signature)

        validate_support_request(request)

    @parameterized.expand(
        [
            ("empty", ""),
            ("text", "not-a-number"),
            ("float_invalid", "12.34.56"),
        ]
    )
    @patch("products.conversations.backend.support_slack.get_support_slack_settings")
    def test_invalid_timestamp_format_raises(self, _name: str, timestamp: str, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_SLACK_SIGNING_SECRET": "test-secret"}

        request = self._make_request(timestamp, "{}", "v0=something")

        with self.assertRaises(SlackIntegrationError):
            validate_support_request(request)
