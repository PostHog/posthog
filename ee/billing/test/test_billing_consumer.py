import json
from datetime import datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog

from ee.billing.queue.BillingConsumer import POSTHOG_SELF_TEAM_ID, BillingConsumer
from ee.models.license import License, LicenseManager

CONSUMER = "ee.billing.queue.BillingConsumer"


class TestBillingConsumerUsageSpike(SimpleTestCase):
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
            "ip_address": "203.0.113.7",
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
        assert log.ip_address == "203.0.113.7"
        assert log.detail is not None
        assert log.detail["changes"][0]["field"] == "product_analytics"
        assert log.detail["changes"][0]["after"] == 1000

    def test_writes_system_activity_when_distinct_id_absent(self):
        # System-origin changes (Stripe webhooks, dunning) carry no actor. Even though the
        # message carries an IP, it must not be pinned to an unattributed system row.
        self._build_consumer()._process_billing_activity(self._message(distinct_id=None))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.user_id is None
        assert log.is_system is True
        assert log.ip_address is None

    def test_does_not_attribute_distinct_id_from_another_organization(self):
        # distinct_id is globally unique; a user outside this org must never be
        # attributed to (or exposed in) this org's audit log.
        other_org = Organization.objects.create(name="Other org")
        other_user = User.objects.create_and_join(other_org, "outsider@example.com", None)

        self._build_consumer()._process_billing_activity(self._message(distinct_id=other_user.distinct_id))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.user_id is None
        assert log.is_system is True
        # A foreign actor is not attributed, so its IP must not be persisted either.
        assert log.ip_address is None

    @parameterized.expand(
        [
            ("empty_string", ""),
            ("garbage", "not-an-ip"),
            ("non_string", 12345),
            ("missing", None),
        ]
    )
    def test_malformed_ip_is_dropped_instead_of_blocking_the_queue(self, _name, bad_ip):
        # A malformed IP must not reach the IP column and fail the write; otherwise the message
        # would loop on redelivery forever. The row is still written, just without an IP.
        self._build_consumer()._process_billing_activity(self._message(ip_address=bad_ip))

        log = ActivityLog.objects.get(scope="Billing")
        assert log.ip_address is None

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


ORG_ID = "0190b3a1-1111-7000-8000-000000000001"
GATEWAY_REQUEST = "posthog.llm.gateway_internal_client.httpx.request"
BILLING_PUT = "ee.billing.billing_manager.http_session.put"


def _envelope(message_type: str = "ai_funding_added", **fields: object) -> dict:
    body = {"type": message_type, "version": 1, "audience": "ai-gateway-us", "organization_id": ORG_ID, **fields}
    return {
        "body": json.dumps(body),
        "signed_at": "2026-11-23T18:04:05Z",
        "key_id": "billing-us-1",
        "signature": "5f0c1e",
    }


def _deliver(body: dict) -> MagicMock:
    with patch("ee.sqs.SQSConsumer.boto3"):
        consumer = BillingConsumer(queue_url="http://example/queue", region_name="us-east-1")
    with patch.object(consumer, "delete_message", return_value=True) as mock_delete:
        consumer.process_message({"Body": json.dumps(body), "MessageId": "msg-1", "ReceiptHandle": "receipt-1"})
    return mock_delete


@override_settings(AI_GATEWAY_INTERNAL_URL="http://gw", AI_GATEWAY_INTERNAL_TOKEN="tok")
class TestBillingConsumerAIGatewayMessage(SimpleTestCase):
    def test_relays_the_envelope_to_the_gateway_and_deletes_the_message(self):
        envelope = _envelope(operation_id="op-1", amount_micros=20_000_000, kind="top_up")
        answer = httpx.Response(200, json={"entry_id": "entry-1", "duplicate": False})
        with patch(GATEWAY_REQUEST, return_value=answer) as mock_post:
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": envelope})

        assert mock_post.call_args.args == ("POST", f"http://gw/internal/accounts/{ORG_ID}/credits")
        assert mock_post.call_args.kwargs["json"] == envelope
        mock_delete.assert_called_once_with("receipt-1")

    @parameterized.expand(
        [
            ("bad_body", 400),
            ("operation_with_another_amount", 409),
            ("unknown_key", 401),
            ("unavailable", 503),
            ("accepted_but_not_a_200", 202),
        ]
    )
    @patch(f"{CONSUMER}.capture_exception")
    def test_any_answer_but_a_200_is_captured_once_and_left_on_the_queue(self, _name, status, mock_capture):
        with patch(GATEWAY_REQUEST, return_value=httpx.Response(status, json={"error": "no"})):
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": _envelope()})

        mock_capture.assert_called_once()
        mock_delete.assert_not_called()

    @parameterized.expand(
        [
            ("unreadable_envelope", {"body": "not json", "signed_at": "x", "key_id": "x", "signature": "x"}),
            ("type_without_a_route", _envelope("ai_reload_requested")),
        ]
    )
    @patch(f"{CONSUMER}.capture_exception")
    def test_a_malformed_message_is_captured_once_and_left_on_the_queue(self, _name, envelope, mock_capture):
        with patch(GATEWAY_REQUEST) as mock_post:
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": envelope})

        mock_post.assert_not_called()
        mock_capture.assert_called_once()
        mock_delete.assert_not_called()


@override_settings(AI_GATEWAY_INTERNAL_URL="http://gw", AI_GATEWAY_INTERNAL_TOKEN="tok")
@patch("ee.billing.billing_manager.BILLING_SERVICE_URL", "http://billing.test")
class TestBillingConsumerAIWithdrawal(BaseTest):
    def setUp(self):
        super().setUp()
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123", plan="enterprise", valid_until=datetime(2038, 1, 19, 3, 14, 7)
        )
        # process_message closes the connection that holds the test's transaction.
        for patcher in (
            patch(f"{CONSUMER}.close_old_connections"),
            patch(f"{CONSUMER}.get_cached_instance_license", return_value=license),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        withdrawal = {
            "organization_id": str(self.organization.id),
            "operation_id": "ai_refund:re_1",
            "amount_micros": 40_000_000,
        }
        self.request = _envelope("ai_withdrawal_requested", reason="refund", **withdrawal)
        self.answer = _envelope("ai_withdrawal_answered", audience="billing", result="approved", **withdrawal)

    def test_passes_the_gateway_answer_to_billing_and_deletes_the_message(self):
        with (
            patch(GATEWAY_REQUEST, return_value=httpx.Response(200, json=self.answer)) as gateway,
            patch(BILLING_PUT, return_value=MagicMock(status_code=200)) as billing,
        ):
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": self.request})

        assert gateway.call_args.args == ("POST", f"http://gw/internal/accounts/{self.organization.id}/withdrawals")
        assert gateway.call_args.kwargs["json"] == self.request
        assert billing.call_args.args[0] == "http://billing.test/api/ai-credits/withdrawals/ai_refund%3Are_1"
        assert billing.call_args.kwargs["json"] == self.answer
        mock_delete.assert_called_once_with("receipt-1")

    @parameterized.expand(
        [
            ("gateway_unavailable", httpx.Response(503, json={}), 0),
            ("gateway_answer_not_signed", httpx.Response(200, json={"result": "approved"}), 0),
            (
                "gateway_answer_without_operation_id",
                httpx.Response(200, json=_envelope("ai_withdrawal_answered", audience="billing", result="approved")),
                0,
            ),
            ("billing_unavailable", None, 1),
        ]
    )
    def test_a_failed_call_leaves_the_message_on_the_queue(self, _name, gateway_answer, billing_calls):
        gateway_answer = gateway_answer or httpx.Response(200, json=self.answer)
        with (
            patch(GATEWAY_REQUEST, return_value=gateway_answer),
            patch(BILLING_PUT, return_value=MagicMock(status_code=503)) as billing,
        ):
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": self.request})

        assert billing.call_count == billing_calls
        mock_delete.assert_not_called()

    @patch(f"{CONSUMER}.capture_exception")
    def test_an_unknown_organization_withdraws_nothing(self, mock_capture):
        request = _envelope("ai_withdrawal_requested", organization_id="01234567-89ab-4def-8123-456789abcdef")
        with patch(GATEWAY_REQUEST) as gateway:
            mock_delete = _deliver({"type": "ai_gateway_message", "envelope": request})

        gateway.assert_not_called()
        mock_capture.assert_called_once()
        mock_delete.assert_not_called()


class TestBillingConsumerUnhandledMessage(SimpleTestCase):
    def _build_consumer(self) -> BillingConsumer:
        with patch("ee.sqs.SQSConsumer.boto3"):
            return BillingConsumer(queue_url="http://example/queue", region_name="us-east-1")

    @parameterized.expand(
        [
            ("invalid_json", "not json", {}),
            ("invalid_gzip", "bm90IGd6aXA=", {"content_encoding": {"StringValue": "gzip"}}),
            ("unknown_type", json.dumps({"type": "ai_withdrawal_requested"}), {}),
        ]
    )
    @patch(f"{CONSUMER}.capture_exception")
    def test_a_message_it_cannot_handle_is_captured_with_its_message_id_and_left_on_the_queue(
        self, _name, raw_body, attributes, mock_capture
    ):
        consumer = self._build_consumer()
        with patch.object(consumer, "delete_message", return_value=True) as mock_delete:
            consumer.process_message(
                {"Body": raw_body, "MessageAttributes": attributes, "MessageId": "msg-1", "ReceiptHandle": "receipt-1"}
            )

        contexts = [call.args[1] for call in mock_capture.call_args_list if len(call.args) > 1]
        self.assertIn("msg-1", [context.get("message_id") for context in contexts])
        mock_delete.assert_not_called()
