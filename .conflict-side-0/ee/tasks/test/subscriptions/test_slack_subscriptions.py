from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription

from ee.tasks.subscriptions.slack_subscriptions import send_slack_subscription_report
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@patch("ee.tasks.subscriptions.slack_subscriptions.SlackIntegration")
@freeze_time("2022-02-02T08:30:00.000Z")
class TestSlackSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    integration: Integration

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.asset = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        self.subscription = create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        self.integration = Integration.objects.create(team=self.team, kind="slack")

    def test_subscription_delivery(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        send_slack_subscription_report(self.subscription, [self.asset], 1)

        assert mock_slack_integration.client.chat_postMessage.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert first_call["channel"] == "C12345"
        assert first_call["text"] == "Your subscription to the Insight *My Test subscription* is ready! 🎉"
        assert first_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Your subscription to the Insight *My Test subscription* is ready! 🎉",
                },
            },
            {
                "type": "image",
                "image_url": post_message_calls[0].kwargs["blocks"][1]["image_url"],
                "alt_text": "My Test subscription",
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog"},
                        "url": "http://localhost:8010/insights/123456?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
                        "url": f"http://localhost:8010/insights/123456/subscriptions/{self.subscription.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                ],
            },
        ]

    def test_subscription_delivery_new(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        send_slack_subscription_report(self.subscription, [self.asset], 1, is_new_subscription=True)

        assert mock_slack_integration.client.chat_postMessage.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert (
            first_call["text"]
            == "This channel has been subscribed to the Insight *My Test subscription* on PostHog! 🎉\nThis subscription is sent every day. The next one will be sent on Wednesday February 02, 2022"
        )

    def test_subscription_dashboard_delivery(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        self.subscription = create_subscription(
            team=self.team,
            dashboard=self.dashboard,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        send_slack_subscription_report(self.subscription, [self.asset, self.asset, self.asset], 10)

        assert mock_slack_integration.client.chat_postMessage.call_count == 4
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert first_call["channel"] == "C12345"
        assert first_call["text"] == "Your subscription to the Dashboard *private dashboard* is ready! 🎉"

        assert first_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Your subscription to the Dashboard *private dashboard* is ready! 🎉",
                },
            },
            {
                "type": "image",
                "image_url": post_message_calls[0].kwargs["blocks"][1]["image_url"],
                "alt_text": "My Test subscription",
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog"},
                        "url": f"http://localhost:8010/dashboard/{self.dashboard.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
                        "url": f"http://localhost:8010/dashboard/{self.dashboard.id}/subscriptions/{self.subscription.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                ],
            },
        ]

        # Second call - other asset
        second_call = post_message_calls[1].kwargs
        assert second_call["channel"] == "C12345"
        assert second_call["thread_ts"] == "1.234"
        assert second_call["blocks"] == [
            {
                "type": "image",
                "image_url": second_call["blocks"][0]["image_url"],
                "alt_text": "My Test subscription",
            }
        ]

        # Third call - other asset
        third_call = post_message_calls[2].kwargs
        assert third_call["blocks"] == [
            {
                "type": "image",
                "image_url": third_call["blocks"][0]["image_url"],
                "alt_text": "My Test subscription",
            }
        ]

        # Fourth call - notice that more exists
        fourth_call = post_message_calls[3].kwargs
        assert fourth_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Showing 3 of 10 Insights. <http://localhost:8010/dashboard/{self.dashboard.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack|View the rest in PostHog>",
                },
            }
        ]

    def test_subscription_delivery_missing_integration(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        self.integration.delete()

        send_slack_subscription_report(self.subscription, [self.asset], 1)

        assert mock_slack_integration.client.chat_postMessage.call_count == 0

        # TODO: Should we perhaps save something to say the Subscription failed?
