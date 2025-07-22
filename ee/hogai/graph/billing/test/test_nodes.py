import datetime
from typing import cast
from unittest.mock import patch
from uuid import uuid4

from ee.hogai.graph.billing.nodes import BillingNode
from ee.hogai.utils.types import AssistantState
from posthog.schema import (
    AssistantToolCallMessage,
    BillingPeriod,
    Interval,
    MaxBillingContext,
    MaxProductInfo,
    Settings1,
    SpendHistoryItem,
    SubscriptionLevel,
    Trial,
    UsageHistoryItem,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestBillingNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.node = BillingNode(self.team, self.user)
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)

    def test_run_with_no_billing_context(self):
        with patch.object(self.node, "_get_billing_context", return_value=None):
            result = self.node.run(self.state, {})
            self.assertEqual(len(result.messages), 1)
            message = result.messages[0]
            self.assertIsInstance(message, AssistantToolCallMessage)
            self.assertEqual(cast(AssistantToolCallMessage, message).content, "No billing information available")

    def test_run_with_billing_context(self):
        billing_context = MaxBillingContext(
            subscription_level=SubscriptionLevel.PAID,
            billing_plan="paid",
            has_active_subscription=True,
            is_deactivated=False,
            settings=Settings1(autocapture_on=True, active_destinations=2),
            products=[],
            addons=[],
        )
        with (
            patch.object(self.node, "_get_billing_context", return_value=billing_context),
            patch.object(self.node, "_format_billing_context", return_value="Formatted Context"),
        ):
            result = self.node.run(self.state, {})
            self.assertEqual(len(result.messages), 1)
            message = result.messages[0]
            self.assertIsInstance(message, AssistantToolCallMessage)
            self.assertEqual(cast(AssistantToolCallMessage, message).content, "Formatted Context")
            self.assertEqual(cast(AssistantToolCallMessage, message).tool_call_id, self.tool_call_id)

    def test_format_billing_context(self):
        billing_context = MaxBillingContext(
            subscription_level=SubscriptionLevel.PAID,
            billing_plan="paid",
            has_active_subscription=True,
            is_deactivated=False,
            billing_period=BillingPeriod(
                current_period_start=str(datetime.date(2023, 1, 1)),
                current_period_end=str(datetime.date(2023, 1, 31)),
                interval=Interval.MONTH,
            ),
            total_current_amount_usd="100.00",
            products=[
                MaxProductInfo(
                    name="Product A",
                    type="type_a",
                    description="Desc A",
                    current_usage=50,
                    usage_limit=100,
                    percentage_usage=0.5,
                    has_exceeded_limit=False,
                    is_used=True,
                )
            ],
            addons=[],
            trial=Trial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
            settings=Settings1(autocapture_on=True, active_destinations=2),
        )

        with patch.object(self.node, "_get_top_events_by_usage", return_value=[]):
            formatted_string = self.node._format_billing_context(billing_context)
            self.assertIn("(paid)", formatted_string)
            self.assertIn("Period: 2023-01-01 to 2023-01-31", formatted_string)

    def test_format_history_table(self):
        usage_history = [
            UsageHistoryItem(
                id=1,
                label="recording_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[100, 200],
                breakdown_type=None,
            ),
            UsageHistoryItem(
                id=2,
                label="event_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[1.5, 2.5],
                breakdown_type=None,
            ),
        ]
        spend_history = [
            SpendHistoryItem(
                id=1,
                label="mobile_recording_count_in_period",
                dates=["2023-01-01", "2023-01-02"],
                data=[10.50, 20.00],
                breakdown_type=None,
            ),
        ]

        usage_table = self.node._format_history_table(usage_history)
        self.assertIn("### Overall (all projects)", usage_table)
        self.assertIn("| Data Type | 2023-01-01 | 2023-01-02 |", usage_table)
        self.assertIn("| Recordings | 100.00 | 200.00 |", usage_table)
        self.assertIn("| Events | 1.50 | 2.50 |", usage_table)

        spend_table = self.node._format_history_table(spend_history)
        self.assertIn("| Mobile Recordings | 10.50 | 20.00 |", spend_table)

    def test_get_top_events_by_usage(self):
        mock_results = [("pageview", 1000), ("$autocapture", 500)]
        with patch("ee.hogai.graph.billing.nodes.sync_execute", return_value=mock_results) as mock_sync_execute:
            top_events = self.node._get_top_events_by_usage()
            self.assertEqual(len(top_events), 2)
            self.assertEqual(top_events[0]["event"], "pageview")
            self.assertEqual(top_events[0]["count"], 1000)
            self.assertEqual(top_events[0]["formatted_count"], "1,000")
            self.assertEqual(top_events[1]["event"], "$autocapture")
            self.assertEqual(top_events[1]["count"], 500)
            self.assertEqual(top_events[1]["formatted_count"], "500")

            mock_sync_execute.assert_called_once()
            # Check team_id is passed correctly
            self.assertIn(str(self.team.pk), str(mock_sync_execute.call_args))

    def test_get_top_events_by_usage_query_fails(self):
        with patch(
            "ee.hogai.graph.billing.nodes.sync_execute", side_effect=Exception("DB connection failed")
        ) as mock_sync_execute:
            top_events = self.node._get_top_events_by_usage()
            self.assertEqual(top_events, [])
            mock_sync_execute.assert_called_once()
