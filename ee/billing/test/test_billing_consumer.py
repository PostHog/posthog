from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.activity_logging.activity_log import ActivityLog

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


class TestBillingConsumerBillingActivity(BaseTest):
    def _build_consumer(self) -> BillingConsumer:
        with patch("ee.sqs.SQSConsumer.boto3"):
            return BillingConsumer(queue_url="http://example/queue", region_name="us-east-1")

    def _message(self, **overrides):
        message = {
            "type": "billing_activity",
            "organization_id": str(self.organization.id),
            "distinct_id": self.user.distinct_id,
            "activity": "updated",
            "item_id": str(self.organization.id),
            "detail": {
                "name": "Billing spend limits",
                "changes": [
                    {
                        "type": "Billing",
                        "action": "changed",
                        "field": "product_analytics",
                        "before": None,
                        "after": 1000,
                    }
                ],
            },
            "event_id": "evt-1",
        }
        message.update(overrides)
        return message

    def test_writes_org_scoped_activity_log_attributed_to_actor(self):
        self._build_consumer()._process_billing_activity(self._message())

        log = ActivityLog.objects.get(scope="Billing")
        assert log.organization_id == self.organization.id
        assert log.team_id is None
        assert log.user_id == self.user.id
        assert log.is_system is False
        assert log.item_id == str(self.organization.id)
        assert log.activity == "updated"
        assert log.detail["changes"][0]["field"] == "product_analytics"
        assert log.detail["changes"][0]["after"] == 1000

    def test_writes_system_activity_when_distinct_id_absent(self):
        # System-origin changes (Stripe webhooks, dunning) carry no actor.
        self._build_consumer()._process_billing_activity(self._message(distinct_id=None))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.user_id is None
        assert log.is_system is True

    @patch(f"{CONSUMER}.capture_exception")
    def test_missing_organization_id_skips_and_captures(self, mock_capture):
        self._build_consumer()._process_billing_activity(self._message(organization_id=None))

        assert not ActivityLog.objects.filter(scope="Billing").exists()
        mock_capture.assert_called_once()
