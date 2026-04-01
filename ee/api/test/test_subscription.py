import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status

from posthog.models import Team
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription
from posthog.temporal.subscriptions.types import ProcessSubscriptionWorkflowInputs

from products.dashboards.backend.models.dashboard import Dashboard

from ee.api.test.base import APILicensedTest
from ee.tasks.subscriptions.slack_subscriptions import get_slack_integration_for_team


@patch("ee.api.subscription.sync_connect")
class TestSubscriptionTemporal(APILicensedTest):
    subscription: Subscription = None  # type: ignore
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    def _create_subscription(self, **kwargs):
        payload = {
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": "2022-01-01T00:00:00",
            "title": "My Subscription",
            "invite_message": "hey there!",
        }

        payload.update(kwargs)
        return self.client.post(f"/api/projects/{self.team.id}/subscriptions", payload)

    @pytest.mark.skip_on_multitenancy
    def test_cannot_list_subscriptions_without_proper_license(self, mock_sync):
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == self.license_required_response(
            "Subscriptions is part of the premium PostHog offering. Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options."
        )

    def test_can_create_new_subscription(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "dashboard": None,
            "insight": self.insight.id,
            "dashboard_export_insights": [],
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "byweekday": None,
            "bysetpos": None,
            "count": None,
            "start_date": "2022-01-01T00:00:00Z",
            "until_date": None,
            "created_at": data["created_at"],
            "created_by": data["created_by"],
            "deleted": False,
            "title": "My Subscription",
            "next_delivery_date": data["next_delivery_date"],
            "integration_id": None,
            "invite_message": None,
            "summary": "sent every week",
        }

        mock_client.start_workflow.assert_called_once()
        wf_args, wf_kwargs = mock_client.start_workflow.call_args
        assert wf_args[0] == "handle-subscription-value-change"
        activity_inputs = wf_args[1]
        assert isinstance(activity_inputs, ProcessSubscriptionWorkflowInputs)
        assert activity_inputs.subscription_id == data["id"]
        assert activity_inputs.invite_message == "hey there!"

    def test_can_create_new_subscription_without_invite_message(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription(invite_message=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        mock_client.start_workflow.assert_called_once()

    def test_can_update_existing_subscription(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription(invite_message=None)
        data = response.json()

        mock_client.start_workflow.assert_called_once()
        mock_client.start_workflow.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{data['id']}",
            {
                "target_value": "test@posthog.com,new_user@posthog.com",
                "invite_message": "hi new user",
            },
        )
        updated_data = response.json()
        assert updated_data["target_value"] == "test@posthog.com,new_user@posthog.com"

        mock_client.start_workflow.assert_called_once()
        wf_args, _ = mock_client.start_workflow.call_args
        activity_inputs = wf_args[1]
        assert activity_inputs.previous_value == "test@posthog.com"
        assert activity_inputs.invite_message == "hi new user"

    def test_can_create_dashboard_subscription_with_dashboard_export_insights(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        self.dashboard.tiles.create(insight=self.insight)
        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [self.insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["dashboard"] == self.dashboard.id
        assert data["dashboard_export_insights"] == [self.insight.id]

    def test_cannot_create_dashboard_subscription_without_dashboard_export_insights(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"

    def test_can_update_subscription_without_providing_dashboard_export_insights(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        self.dashboard.tiles.create(insight=self.insight)
        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [self.insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        subscription_id = response.json()["id"]

        # Update without providing dashboard_export_insights - should succeed
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"title": "Updated Title"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated Title"
        assert response.json()["dashboard_export_insights"] == [self.insight.id]

    def test_can_update_dashboard_subscription_with_new_insights(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        insight_1 = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )
        insight_2 = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )
        self.dashboard.tiles.create(insight=insight_1)
        self.dashboard.tiles.create(insight=insight_2)

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [insight_1.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        subscription_id = response.json()["id"]
        assert response.json()["dashboard_export_insights"] == [insight_1.id]

        # Update to include both insights
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"dashboard_export_insights": [insight_1.id, insight_2.id]},
        )
        assert response.status_code == status.HTTP_200_OK
        assert sorted(response.json()["dashboard_export_insights"]) == sorted([insight_1.id, insight_2.id])

    def test_cannot_clear_dashboard_export_insights_on_dashboard_subscription(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        self.dashboard.tiles.create(insight=self.insight)
        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [self.insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        subscription_id = response.json()["id"]

        # Try to clear dashboard_export_insights - should fail
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"dashboard_export_insights": []},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"

    def test_cannot_create_dashboard_subscription_with_too_many_insights(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        insights = []
        for _ in range(7):
            insight = Insight.objects.create(
                filters=Filter(data=self.insight_filter_dict).to_dict(),
                team=self.team,
                created_by=self.user,
            )
            self.dashboard.tiles.create(insight=insight)
            insights.append(insight)

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [i.id for i in insights],  # exceeds limit
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"
        assert "Cannot select more than 6 insights" in response.json()["detail"]

    def test_cannot_create_dashboard_subscription_with_insights_from_other_dashboard(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        # Create an insight that belongs to a different dashboard
        other_dashboard = Dashboard.objects.create(team=self.team, name="other dashboard", created_by=self.user)
        other_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )
        other_dashboard.tiles.create(insight=other_insight)

        self.dashboard.tiles.create(insight=self.insight)
        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [self.insight.id, other_insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"
        assert "1 invalid insight(s) selected" in response.json()["detail"]

    def test_cannot_set_dashboard_export_insights_on_insight_subscription(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "insight": self.insight.id,
                "dashboard_export_insights": [self.insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Insight Subscription",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"
        assert "Cannot set insights selection without a dashboard" in response.json()["detail"]

    def test_cannot_create_dashboard_subscription_with_insights_from_other_team(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        # Create another team and insight
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=other_team,
            created_by=self.user,
        )

        self.dashboard.tiles.create(insight=self.insight)
        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [other_insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard Subscription",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "dashboard_export_insights"
        assert "do not belong to your team" in response.json()["detail"]

    def test_can_create_slack_subscription_with_valid_integration(self, mock_sync):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        integration = Integration.objects.create(team=self.team, kind="slack", config={})
        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=integration.id,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["integration_id"] == integration.id

    def test_cannot_create_slack_subscription_without_integration(self, mock_sync):
        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "required for Slack subscriptions" in response.json()["detail"]

    def test_cannot_create_subscription_with_other_teams_integration(self, mock_sync):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_integration = Integration.objects.create(team=other_team, kind="slack", config={})

        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=other_integration.id,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong to your team" in response.json()["detail"]

    def test_cannot_create_slack_subscription_with_non_slack_integration(self, mock_sync):
        integration = Integration.objects.create(team=self.team, kind="hubspot", config={})

        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=integration.id,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "require a Slack integration" in response.json()["detail"]

    def test_backfill_picks_same_integration_as_delivery(self, mock_sync):
        """The data migration must assign the lowest-id Slack integration
        per team, matching get_slack_integration_for_team behavior."""
        import importlib

        from django.apps import apps
        from django.utils import timezone

        migration = importlib.import_module("posthog.migrations.1041_backfill_subscription_integration")

        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client

        # Team 1: two slack integrations
        integration_a = Integration.objects.create(team=self.team, kind="slack", config={"a": 1})
        Integration.objects.create(team=self.team, kind="slack", config={"b": 2})

        # Team 2: its own slack integration (higher id than team 1's)
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=other_team,
            created_by=self.user,
        )
        other_integration = Integration.objects.create(team=other_team, kind="slack", config={"c": 3})

        sub_team1 = Subscription.objects.create(
            team=self.team,
            insight=self.insight,
            target_type="slack",
            target_value="C1234|#general",
            frequency="weekly",
            interval=1,
            start_date=timezone.now(),
            title="Slack Sub Team 1",
        )
        sub_team2 = Subscription.objects.create(
            team=other_team,
            insight=other_insight,
            target_type="slack",
            target_value="C5678|#alerts",
            frequency="weekly",
            interval=1,
            start_date=timezone.now(),
            title="Slack Sub Team 2",
        )

        # Run the actual backfill migration function
        migration.backfill_subscription_integration(apps, None)

        sub_team1.refresh_from_db()
        sub_team2.refresh_from_db()

        # Each subscription got its own team's integration, not a global lowest id
        assert sub_team1.integration_id == integration_a.id
        assert sub_team2.integration_id == other_integration.id

        # And both match what get_slack_integration_for_team would return
        delivery_team1 = get_slack_integration_for_team(self.team.id)
        delivery_team2 = get_slack_integration_for_team(other_team.id)
        assert delivery_team1 is not None
        assert delivery_team2 is not None
        assert sub_team1.integration_id == delivery_team1.id
        assert sub_team2.integration_id == delivery_team2.id
