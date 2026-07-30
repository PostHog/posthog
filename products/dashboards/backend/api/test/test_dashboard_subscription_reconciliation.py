from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.models.insight import Insight


class TestDashboardSubscriptionReconciliation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Dashboard")
        self.first_insight = Insight.objects.create(team=self.team, name="First")
        self.second_insight = Insight.objects.create(team=self.team, name="Second")
        self.first_tile = DashboardTile.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            insight=self.first_insight,
        )
        DashboardTile.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            insight=self.second_insight,
        )

    def _subscription(self, *insights: Insight) -> Subscription:
        subscription = Subscription.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            target_type=Subscription.SubscriptionTarget.EMAIL,
            target_value=self.user.email,
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            start_date=timezone.now(),
            created_by=self.user,
        )
        subscription.dashboard_export_insights.set(insights)
        return subscription

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_delete_tile_removes_one_of_multiple_selections(self, _create_notification) -> None:
        subscription = self._subscription(self.first_insight, self.second_insight)

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/delete_tile",
            {"tile_id": self.first_tile.id},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        subscription.refresh_from_db()
        assert subscription.enabled
        assert list(subscription.dashboard_export_insights.values_list("id", flat=True)) == [self.second_insight.id]

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_dashboard_patch_pauses_final_selection_without_clearing_it(self, _create_notification) -> None:
        subscription = self._subscription(self.first_insight)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}",
            {"tiles": [{"id": self.first_tile.id, "deleted": True}]},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        subscription.refresh_from_db()
        assert not subscription.enabled
        assert list(subscription.dashboard_export_insights.values_list("id", flat=True)) == [self.first_insight.id]

    @patch(
        "products.dashboards.backend.api.dashboard.reconcile_dashboard_subscriptions",
        side_effect=RuntimeError("reconciliation failed"),
    )
    def test_delete_tile_rolls_back_when_reconciliation_fails(self, _reconcile) -> None:
        self._subscription(self.first_insight)

        with self.assertRaises(RuntimeError):
            self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/delete_tile",
                {"tile_id": self.first_tile.id},
            )

        self.first_tile.refresh_from_db()
        assert not self.first_tile.deleted

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_dashboard_deletion_pauses_explicit_subscription(self, _create_notification) -> None:
        subscription = self._subscription(self.first_insight)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}",
            {"deleted": True},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        subscription.refresh_from_db()
        assert not subscription.enabled
        assert list(subscription.dashboard_export_insights.values_list("id", flat=True)) == [self.first_insight.id]
