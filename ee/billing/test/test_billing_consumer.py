import gzip
import json
import base64

from posthog.test.base import BaseTest
from unittest.mock import patch

from ee.billing.queue.BillingConsumer import (
    BILLING_COLLECTIONS_ACCESS_BLOCK_REASON,
    BILLING_COLLECTIONS_INACTIVE_REASON,
    POSTHOG_SELF_TEAM_ID,
    BillingConsumer,
)

CONSUMER = "ee.billing.queue.BillingConsumer"


class TestBillingConsumerUsageSpike(BaseTest):
    def _build_consumer(self) -> BillingConsumer:
        with patch("ee.sqs.SQSConsumer.boto3"):
            return BillingConsumer(queue_url="http://example/queue", region_name="us-east-1")

    @patch(f"{CONSUMER}.notify_managers_of_usage_spike")
    def test_dispatches_usage_spike(self, mock_notify):
        self._build_consumer()._process_usage_spike_detected(
            {
                "type": "usage_spike_detected",
                "data": {
                    "spike_id": "spike-1",
                    "organization_id": "org-1",
                    "spikes": [{"metric": "events", "factor": 3}],
                    "detected_at": "2026-06-09",
                },
            }
        )
        mock_notify.assert_called_once_with(
            team_id=POSTHOG_SELF_TEAM_ID,
            spike_id="spike-1",
            spikes=[{"metric": "events", "factor": 3}],
            organization_id="org-1",
            billing_id=None,
            stripe_customer_id=None,
            detected_at="2026-06-09",
        )

    @patch(f"{CONSUMER}.capture_exception")
    @patch(f"{CONSUMER}.notify_managers_of_usage_spike")
    def test_missing_spike_id_skips_and_captures(self, mock_notify, mock_capture):
        self._build_consumer()._process_usage_spike_detected({"data": {"organization_id": "org-1"}})
        mock_notify.assert_not_called()
        mock_capture.assert_called_once()


class TestBillingConsumerCollectionsAccess(BaseTest):
    def _build_consumer(self) -> BillingConsumer:
        with patch("ee.sqs.SQSConsumer.boto3"):
            return BillingConsumer(queue_url="http://example/queue", region_name="us-east-1")

    def _message(self, desired_state: str = "blocked", **overrides):
        body = {
            "type": "billing_collections_access_state_changed",
            "organization_id": str(self.organization.id),
            "customer_id": "cus_billing_123",
            "data": {
                "stripe_customer_id": "cus_stripe_123",
                "desired_state": desired_state,
                "reason": BILLING_COLLECTIONS_ACCESS_BLOCK_REASON,
            },
        }
        body.update(overrides)
        return body

    def test_block_active_org(self):
        self.organization.customer_id = "cus_billing_123"
        self.organization.save()

        self._build_consumer()._process_collections_access_state_changed(self._message())

        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == BILLING_COLLECTIONS_INACTIVE_REASON

    def test_duplicate_block_is_idempotent(self):
        self.organization.customer_id = "cus_billing_123"
        self.organization.save()

        consumer = self._build_consumer()
        consumer._process_collections_access_state_changed(self._message())
        consumer._process_collections_access_state_changed(self._message())

        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == BILLING_COLLECTIONS_INACTIVE_REASON

    def test_unblock_billing_collections_org(self):
        self.organization.customer_id = "cus_billing_123"
        self.organization.is_active = False
        self.organization.is_not_active_reason = BILLING_COLLECTIONS_INACTIVE_REASON
        self.organization.save()

        self._build_consumer()._process_collections_access_state_changed(self._message("unblocked"))

        self.organization.refresh_from_db()
        assert self.organization.is_active is True
        assert self.organization.is_not_active_reason is None

    def test_block_leaves_manual_inactive_org_inactive(self):
        self.organization.customer_id = "cus_billing_123"
        self.organization.is_active = False
        self.organization.is_not_active_reason = "Manual deactivation"
        self.organization.save()

        self._build_consumer()._process_collections_access_state_changed(self._message("blocked"))

        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == "Manual deactivation"

    def test_unblock_leaves_manual_inactive_org_inactive(self):
        self.organization.customer_id = "cus_billing_123"
        self.organization.is_active = False
        self.organization.is_not_active_reason = "Manual deactivation"
        self.organization.save()

        self._build_consumer()._process_collections_access_state_changed(self._message("unblocked"))

        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == "Manual deactivation"

    @patch(f"{CONSUMER}.capture_exception")
    def test_customer_mismatch_is_ignored(self, mock_capture):
        self.organization.customer_id = "different_customer"
        self.organization.save()

        self._build_consumer()._process_collections_access_state_changed(self._message())

        self.organization.refresh_from_db()
        assert self.organization.is_active is True
        mock_capture.assert_called_once()

    @patch(f"{CONSUMER}.capture_exception")
    def test_missing_required_fields_are_ignored(self, mock_capture):
        self.organization.customer_id = "cus_billing_123"
        self.organization.save()

        message = self._message()
        del message["data"]["reason"]

        self._build_consumer()._process_collections_access_state_changed(message)

        self.organization.refresh_from_db()
        assert self.organization.is_active is True
        mock_capture.assert_called_once()

    @patch(f"{CONSUMER}.close_old_connections")
    @patch.object(BillingConsumer, "delete_message", return_value=True)
    def test_process_message_dispatches_collections_access_state_change(self, mock_delete_message, mock_close):
        self.organization.customer_id = "cus_billing_123"
        self.organization.save()
        body = json.dumps(self._message()).encode("utf-8")
        compressed_body = base64.b64encode(gzip.compress(body)).decode("ascii")

        self._build_consumer().process_message(
            {
                "Body": compressed_body,
                "MessageId": "msg-1",
                "ReceiptHandle": "receipt-1",
                "MessageAttributes": {
                    "content_encoding": {"StringValue": "gzip"},
                    "content_type": {"StringValue": "application/json"},
                },
            }
        )

        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        mock_delete_message.assert_called_once_with("receipt-1")
