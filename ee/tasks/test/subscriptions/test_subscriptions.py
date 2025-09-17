from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, call, patch

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting

from ee.tasks.subscriptions import (
    deliver_subscription_report,
    handle_subscription_value_change,
    schedule_all_subscriptions,
)
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@patch("ee.tasks.subscriptions.send_slack_subscription_report")
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestSubscriptionsTasks(APIBaseTest):
    dashboard: Dashboard
    insight: Insight
    tiles: list[DashboardTile] = None  # type: ignore
    asset: ExportedAsset

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.asset = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        self.tiles = []
        for i in range(10):
            insight = Insight.objects.create(team=self.team, short_id=f"{i}23456{i}", name=f"insight {i}")
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=insight))

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    @patch("ee.tasks.subscriptions.deliver_subscription_report")
    def test_subscription_delivery_scheduling(
        self,
        mock_deliver_task: MagicMock,
        mock_gen_assets: MagicMock,
        mock_send_email: MagicMock,
        mock_send_slack: MagicMock,
    ) -> None:
        with freeze_time("2022-02-02T08:30:00.000Z"):  # Create outside of buffer before running
            subscriptions = [
                create_subscription(team=self.team, insight=self.insight, created_by=self.user),
                create_subscription(team=self.team, insight=self.insight, created_by=self.user),
                create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user),
                create_subscription(
                    team=self.team,
                    dashboard=self.dashboard,
                    created_by=self.user,
                    deleted=True,
                ),
            ]
        # Modify a subscription to have its target time at least an hour ahead
        subscriptions[2].start_date = datetime(2022, 1, 1, 10, 0).replace(tzinfo=ZoneInfo("UTC"))
        subscriptions[2].save()
        assert subscriptions[2].next_delivery_date == datetime(2022, 2, 2, 10, 0).replace(tzinfo=ZoneInfo("UTC"))

        schedule_all_subscriptions()

        self.assertCountEqual(
            mock_deliver_task.delay.call_args_list, [call(subscriptions[0].id), call(subscriptions[1].id)]
        )

    @patch("ee.tasks.subscriptions.deliver_subscription_report")
    def test_does_not_schedule_subscription_if_item_is_deleted(
        self,
        mock_deliver_task: MagicMock,
        mock_gen_assets: MagicMock,
        mock_send_email: MagicMock,
        mock_send_slack: MagicMock,
    ) -> None:
        create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        create_subscription(
            team=self.team,
            dashboard=self.dashboard,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        self.insight.deleted = True
        self.insight.save()
        self.dashboard.deleted = True
        self.dashboard.save()

        schedule_all_subscriptions()

        assert mock_deliver_task.delay.call_count == 0

    def test_deliver_subscription_report_email(
        self,
        mock_gen_assets: MagicMock,
        mock_send_email: MagicMock,
        mock_send_slack: MagicMock,
    ) -> None:
        subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)
        mock_gen_assets.return_value = [self.insight], [self.asset]

        deliver_subscription_report(subscription.id)

        assert mock_send_email.call_count == 2

        assert mock_send_email.call_args_list == [
            call(
                "test1@posthog.com",
                subscription,
                [self.asset],
                invite_message=None,
                total_asset_count=1,
            ),
            call(
                "test2@posthog.com",
                subscription,
                [self.asset],
                invite_message=None,
                total_asset_count=1,
            ),
        ]

    def test_handle_subscription_value_change_email(
        self,
        mock_gen_assets: MagicMock,
        mock_send_email: MagicMock,
        mock_send_slack: MagicMock,
    ) -> None:
        subscription = create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_value="test_existing@posthog.com,test_new@posthog.com",
        )
        mock_gen_assets.return_value = [self.insight], [self.asset]

        handle_subscription_value_change(
            subscription.id,
            previous_value="test_existing@posthog.com",
            invite_message="My invite message",
        )

        assert mock_send_email.call_count == 1

        assert mock_send_email.call_args_list == [
            call(
                "test_new@posthog.com",
                subscription,
                [self.asset],
                invite_message="My invite message",
                total_asset_count=1,
            )
        ]

    def test_deliver_subscription_report_slack(
        self,
        mock_gen_assets: MagicMock,
        mock_send_email: MagicMock,
        mock_send_slack: MagicMock,
    ) -> None:
        subscription = create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )
        mock_gen_assets.return_value = [self.insight], [self.asset]

        deliver_subscription_report(subscription.id)

        assert mock_send_slack.call_count == 1
        assert mock_send_slack.call_args_list == [
            call(
                subscription,
                [self.asset],
                total_asset_count=1,
                is_new_subscription=False,
            )
        ]
