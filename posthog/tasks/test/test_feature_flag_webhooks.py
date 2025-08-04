import json
from unittest.mock import patch
from celery.exceptions import Retry
import pytest
import requests
import responses

from posthog.tasks.feature_flag_webhooks import (
    send_single_feature_flag_webhook_task,
    send_all_feature_flag_webhooks,
    send_feature_flag_webhook,
)
from posthog.test.base import BaseTest


class TestFeatureFlagWebhookTasks(BaseTest):
    def setUp(self):
        super().setUp()
        self.webhook_url = "https://webhook.example.com/webhook"
        self.payload = {
            "event": "feature_flag_changed",
            "change_type": "updated",
            "feature_flag": {
                "id": 1,
                "key": "test-flag",
                "name": "Test Flag",
                "active": True,
            },
            "team": {
                "id": self.team.pk,
                "name": self.team.name,
            },
        }
        self.custom_headers = {"Authorization": "Bearer token123"}

    @responses.activate
    def test_send_feature_flag_webhook_success(self):
        """Test successful webhook sending"""
        responses.add(
            responses.POST,
            self.webhook_url,
            json={"status": "ok"},
            status=200,
        )

        result = send_feature_flag_webhook(
            webhook_url=self.webhook_url,
            payload=self.payload,
            custom_headers=self.custom_headers,
            retry_count=0,
        )

        assert result is True
        assert len(responses.calls) == 1

        # Check request details
        request = responses.calls[0].request
        assert request.url == self.webhook_url
        assert json.loads(request.body) == self.payload
        assert "application/json" in request.headers["Content-Type"]
        assert "PostHog-Webhooks" in request.headers["User-Agent"]
        assert request.headers["X-PostHog-Event"] == "feature_flag_changed"

    @responses.activate
    def test_send_feature_flag_webhook_failure(self):
        """Test webhook failure handling"""
        responses.add(
            responses.POST,
            self.webhook_url,
            json={"error": "Invalid request"},
            status=400,
        )

        result = send_feature_flag_webhook(
            webhook_url=self.webhook_url,
            payload=self.payload,
            retry_count=1,
        )

        assert result is False

    @responses.activate
    def test_send_feature_flag_webhook_timeout(self):
        """Test webhook timeout handling"""
        responses.add(
            responses.POST,
            self.webhook_url,
            body=requests.exceptions.ConnectionError("Connection timeout"),
        )

        result = send_feature_flag_webhook(
            webhook_url=self.webhook_url,
            payload=self.payload,
            retry_count=0,
        )

        assert result is False

    @responses.activate
    @patch(
        "posthog.tasks.feature_flag_webhooks.decrypt_webhook_headers",
        return_value={"Authorization": "Bearer decrypted-token"},
    )
    def test_send_feature_flag_webhook_with_encrypted_headers(self, mock_decrypt):
        """Test webhook with encrypted headers"""
        # mock_decrypt.return_value = {"Authorization": "Bearer decrypted-token"}
        responses.add(responses.POST, self.webhook_url, json={"status": "ok"}, status=200)

        encrypted_headers = {"Authorization": "encrypted-token-data"}
        result = send_feature_flag_webhook(
            webhook_url=self.webhook_url,
            payload=self.payload,
            custom_headers=encrypted_headers,
        )

        assert result is True
        mock_decrypt.assert_called_once_with(encrypted_headers)

        # Check that decrypted headers were used
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer decrypted-token"

    @patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.delay")
    def test_send_all_feature_flag_webhooks_dispatch(self, mock_delay):
        """Test that send_all_feature_flag_webhooks properly dispatches tasks"""
        webhook_subscriptions = [
            {"url": "https://webhook1.example.com", "headers": {"key": "value1"}},
            {"url": "https://webhook2.example.com", "headers": {"key": "value2"}},
            {"url": "  ", "headers": {}},  # Should be skipped (empty URL)
            {"url": "invalid-url", "headers": {}},  # Should be skipped (invalid format)
        ]

        send_all_feature_flag_webhooks(webhook_subscriptions, self.payload)

        # Should only dispatch 2 tasks (skip empty and invalid URLs)
        assert mock_delay.call_count == 2

        # Check first call
        mock_delay.assert_any_call(
            webhook_url="https://webhook1.example.com",
            payload=self.payload,
            custom_headers={"key": "value1"},
        )

        # Check second call
        mock_delay.assert_any_call(
            webhook_url="https://webhook2.example.com",
            payload=self.payload,
            custom_headers={"key": "value2"},
        )

    @patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.delay")
    @patch("posthog.tasks.feature_flag_webhooks.send_feature_flag_webhook")
    def test_send_all_feature_flag_webhooks_fallback(self, mock_sync_send, mock_delay):
        """Test fallback to synchronous sending when task dispatch fails"""
        mock_delay.side_effect = Exception("Celery not available")

        webhook_subscriptions = [{"url": "https://webhook.example.com", "headers": {}}]

        send_all_feature_flag_webhooks(webhook_subscriptions, self.payload)

        # Should attempt task dispatch first
        mock_delay.assert_called_once()

        # Should fall back to synchronous execution
        mock_sync_send.assert_called_once_with(
            webhook_url="https://webhook.example.com",
            payload=self.payload,
            custom_headers={},
            retry_count=0,
        )

    def test_send_all_feature_flag_webhooks_empty_list(self):
        """Test that empty webhook list returns early"""
        with patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.delay") as mock_delay:
            send_all_feature_flag_webhooks([], self.payload)
            mock_delay.assert_not_called()

    @responses.activate
    def test_send_single_feature_flag_webhook_task_success(self):
        """Test successful webhook task execution"""
        responses.add(responses.POST, self.webhook_url, json={"status": "ok"}, status=200)

        send_single_feature_flag_webhook_task(
            self.webhook_url,
            self.payload,
            self.custom_headers,
        )

        # Should complete without raising exception
        assert len(responses.calls) == 1

    @responses.activate
    @patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.retry")
    def test_send_single_feature_flag_webhook_task_retry(self, mock_retry):
        """Test webhook task retry logic"""
        responses.add(responses.POST, self.webhook_url, status=500)  # Server error

        mock_retry.side_effect = Retry("Retrying...")

        with pytest.raises(Retry):
            send_single_feature_flag_webhook_task(
                self.webhook_url,
                self.payload,
                self.custom_headers,
            )

        # Should call retry with exponential backoff
        mock_retry.assert_called_once_with(countdown=2)  # RETRY_DELAY * (2^0)

    @responses.activate
    @patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.retry")
    @patch("celery.app.task.Task.request")
    def test_send_single_feature_flag_webhook_task_max_retries(self, mock_request, mock_retry):
        """Test webhook task when max retries reached"""
        responses.add(responses.POST, self.webhook_url, status=500)

        mock_request.retries = 2
        mock_retry.side_effect = Retry("Max retries exceeded")

        with pytest.raises(Retry):
            send_single_feature_flag_webhook_task(
                self.webhook_url,
                self.payload,
                self.custom_headers,
            )

        # Should still attempt retry (Celery handles max retry enforcement)
        mock_retry.assert_called_once_with(countdown=8)  # RETRY_DELAY * (2^2)

    @patch("posthog.tasks.feature_flag_webhooks.send_single_feature_flag_webhook_task.retry")
    def test_send_single_feature_flag_webhook_task_retry_exception_passthrough(self, mock_retry):
        """Test that Retry exceptions are properly re-raised"""

        with patch("posthog.tasks.feature_flag_webhooks.send_feature_flag_webhook") as mock_send:
            # Simulate Celery retry being raised from within the function
            mock_send.side_effect = Retry("Celery retry")

            with pytest.raises(Retry):
                send_single_feature_flag_webhook_task(
                    self.webhook_url,
                    self.payload,
                    self.custom_headers,
                )

            # Should not call task.retry since Retry was already raised
            mock_retry.assert_not_called()
