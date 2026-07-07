from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Organization, User
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
        assert log.detail is not None
        assert log.detail["changes"][0]["field"] == "product_analytics"
        assert log.detail["changes"][0]["after"] == 1000

    def test_writes_system_activity_when_distinct_id_absent(self):
        # System-origin changes (Stripe webhooks, dunning) carry no actor.
        self._build_consumer()._process_billing_activity(self._message(distinct_id=None))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.user_id is None
        assert log.is_system is True

    def test_does_not_attribute_distinct_id_from_another_organization(self):
        # distinct_id is globally unique; a user outside this org must never be
        # attributed to (or exposed in) this org's audit log.
        other_org = Organization.objects.create(name="Other org")
        other_user = User.objects.create_and_join(other_org, "outsider@example.com", None)

        self._build_consumer()._process_billing_activity(self._message(distinct_id=other_user.distinct_id))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.user_id is None
        assert log.is_system is True

    @patch(f"{CONSUMER}.capture_exception")
    def test_missing_organization_id_skips_and_captures(self, mock_capture):
        self._build_consumer()._process_billing_activity(self._message(organization_id=None))

        assert not ActivityLog.objects.filter(scope="Billing").exists()
        mock_capture.assert_called_once()

    def test_acks_updated_activity_with_no_changes(self):
        # An "updated" message with nothing to record must be acked (no write, no raise) so it
        # is not retried forever; otherwise the raise-on-failure path below would loop on it.
        message = self._message()
        message["detail"] = {"name": "Billing spend limits", "changes": []}

        self._build_consumer()._process_billing_activity(message)

        assert not ActivityLog.objects.filter(scope="Billing").exists()

    @patch(f"{CONSUMER}.log_activity", return_value=None)
    def test_raises_when_write_fails_so_message_is_retried(self, _mock_log_activity):
        # log_activity returns None on write failure in production; the consumer must raise so
        # process_message leaves the message for SQS to redeliver instead of dropping the audit.
        with self.assertRaises(Exception):
            self._build_consumer()._process_billing_activity(self._message())
