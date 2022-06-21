from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription
from posthog.tasks.subscriptions.slack_subscriptions import send_slack_subscription_report
from posthog.tasks.test.subscriptions.utils_subscription_tests import create_subscription
from posthog.test.base import APIBaseTest


@patch("posthog.tasks.subscriptions.slack_subscriptions.SlackIntegration")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestSlackSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset

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

        Integration.objects.create(team=self.team, kind="slack")

    def test_subscription_delivery(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        send_slack_subscription_report(self.subscription, [self.asset], 1)

        assert mock_slack_integration.client.chat_postMessage.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list

        assert post_message_calls[0].kwargs == {}
