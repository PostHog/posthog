from posthog.test.base import BaseTest
from unittest.mock import patch

from ee.billing.queue.BillingConsumer import POSTHOG_SELF_TEAM_ID, BillingConsumer

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
