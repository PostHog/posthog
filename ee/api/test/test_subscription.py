from datetime import UTC, datetime
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription, SubscriptionDelivery
from posthog.temporal.subscriptions.types import ProcessSubscriptionWorkflowInputs, SubscriptionTriggerType

from products.dashboards.backend.models.dashboard import Dashboard

from ee.api.test.base import APILicensedTest
from ee.tasks.subscriptions.slack_subscriptions import get_slack_integration_for_team


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

    def setUp(self):
        super().setUp()
        self._sync_connect_patcher = patch("ee.api.subscription.sync_connect")
        self.mock_sync = self._sync_connect_patcher.start()
        self.mock_temporal_client = MagicMock()
        self.mock_temporal_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = self.mock_temporal_client
        self.addCleanup(self._sync_connect_patcher.stop)

    @pytest.mark.skip_on_multitenancy
    def test_cannot_list_subscriptions_without_proper_license(self):
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == self.license_required_response(
            "Subscriptions is part of the premium PostHog offering. Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options."
        )

    def test_can_create_new_subscription(self):
        response = self._create_subscription()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "dashboard": None,
            "insight": self.insight.id,
            "insight_short_id": self.insight.short_id,
            # Serializer uses f"{name or derived_name}"; when both are None that is the string "None", not null.
            "resource_name": data["resource_name"],
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
            "summary_enabled": False,
            "summary_prompt_guide": "",
        }

        self.mock_temporal_client.start_workflow.assert_called_once()
        wf_args, wf_kwargs = self.mock_temporal_client.start_workflow.call_args
        assert wf_args[0] == "handle-subscription-value-change"
        activity_inputs = wf_args[1]
        assert isinstance(activity_inputs, ProcessSubscriptionWorkflowInputs)
        assert activity_inputs.subscription_id == data["id"]
        assert activity_inputs.invite_message == "hey there!"

    def test_can_create_new_subscription_without_invite_message(self):
        response = self._create_subscription(invite_message=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.mock_temporal_client.start_workflow.assert_called_once()

    def test_can_update_existing_subscription(self):
        response = self._create_subscription(invite_message=None)
        data = response.json()

        self.mock_temporal_client.start_workflow.assert_called_once()
        self.mock_temporal_client.start_workflow.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{data['id']}",
            {
                "target_value": "test@posthog.com,new_user@posthog.com",
                "invite_message": "hi new user",
            },
        )
        updated_data = response.json()
        assert updated_data["target_value"] == "test@posthog.com,new_user@posthog.com"

        self.mock_temporal_client.start_workflow.assert_called_once()
        wf_args, _ = self.mock_temporal_client.start_workflow.call_args
        activity_inputs = wf_args[1]
        assert activity_inputs.previous_value == "test@posthog.com"
        assert activity_inputs.invite_message == "hi new user"

    def test_can_create_dashboard_subscription_with_dashboard_export_insights(self):
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

    def test_cannot_create_dashboard_subscription_without_dashboard_export_insights(self):
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

    def test_can_update_subscription_without_providing_dashboard_export_insights(self):
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

    def test_can_update_dashboard_subscription_with_new_insights(self):
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

    def test_cannot_clear_dashboard_export_insights_on_dashboard_subscription(self):
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

    def test_cannot_create_dashboard_subscription_with_too_many_insights(self):
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

    def test_cannot_create_dashboard_subscription_with_insights_from_other_dashboard(self):
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

    def test_cannot_set_dashboard_export_insights_on_insight_subscription(self):
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

    def test_cannot_create_dashboard_subscription_with_insights_from_other_team(self):
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

    def test_can_create_slack_subscription_with_valid_integration(self):
        integration = Integration.objects.create(team=self.team, kind="slack", config={})
        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=integration.id,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["integration_id"] == integration.id

    def test_cannot_create_slack_subscription_without_integration(self):
        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "required for Slack subscriptions" in response.json()["detail"]

    def test_cannot_create_subscription_with_other_teams_integration(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_integration = Integration.objects.create(team=other_team, kind="slack", config={})

        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=other_integration.id,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong to your team" in response.json()["detail"]

    def test_cannot_create_slack_subscription_with_non_slack_integration(self):
        integration = Integration.objects.create(team=self.team, kind="hubspot", config={})

        response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=integration.id,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "require a Slack integration" in response.json()["detail"]

    def test_cannot_create_subscription_with_summary_enabled_without_ai_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self._create_subscription(summary_enabled=True)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.json()["detail"]
        self.mock_temporal_client.start_workflow.assert_not_called()

    def test_can_create_subscription_with_summary_enabled_when_ai_consent_given(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self._create_subscription(summary_enabled=True)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["summary_enabled"] is True

    def test_cannot_patch_summary_enabled_true_without_ai_consent(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        create_response = self._create_subscription()
        subscription_id = create_response.json()["id"]

        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"summary_enabled": True},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.json()["detail"]

    def test_can_patch_unrelated_fields_when_summary_enabled_and_ai_consent_revoked(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        create_response = self._create_subscription(summary_enabled=True)
        subscription_id = create_response.json()["id"]

        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"title": "Updated title"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated title"

    def test_deliver_subscription(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]
        mock_client.start_workflow.reset_mock()

        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_202_ACCEPTED

        # start_workflow is called twice: once for the create (target change) and once for test-delivery
        assert mock_client.start_workflow.call_count == 1
        wf_args, wf_kwargs = mock_client.start_workflow.call_args
        assert wf_args[0] == "handle-subscription-value-change"
        activity_inputs = wf_args[1]
        assert isinstance(activity_inputs, ProcessSubscriptionWorkflowInputs)
        assert activity_inputs.subscription_id == sub_id
        assert activity_inputs.previous_value is None
        assert activity_inputs.trigger_type == SubscriptionTriggerType.MANUAL
        assert wf_kwargs["id"] == f"test-delivery-subscription-{sub_id}"

    def test_deliver_cross_team_returns_404(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        response = self.client.post(f"/api/projects/{other_team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_deliver_deleted_subscription_returns_404(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]
        Subscription.objects.filter(id=sub_id).update(deleted=True)

        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_deliver_temporal_error_returns_500(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(side_effect=[None, RuntimeError("Temporal unavailable")])
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]

        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to schedule delivery"

    def test_deliver_concurrent_returns_409(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(
            side_effect=[
                None,  # create subscription
                WorkflowAlreadyStartedError(
                    "test-delivery-subscription-1", "handle-subscription-value-change"
                ),  # test-delivery
            ]
        )
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]

        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_backfill_picks_same_integration_as_delivery(self):
        """The data migration must assign the lowest-id Slack integration
        per team, matching get_slack_integration_for_team behavior."""
        import importlib

        from django.apps import apps
        from django.utils import timezone

        migration = importlib.import_module("posthog.migrations.1041_backfill_subscription_integration")

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

    def test_list_subscriptions_defaults_to_newest_created_first(self):
        r1 = self._create_subscription(title="Older")
        assert r1.status_code == status.HTTP_201_CREATED
        first_id = r1.json()["id"]

        r2 = self._create_subscription(title="Newer")
        assert r2.status_code == status.HTTP_201_CREATED
        second_id = r2.json()["id"]

        list_res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/")
        assert list_res.status_code == status.HTTP_200_OK
        results = list_res.json()["results"]
        ids = [row["id"] for row in results]
        assert ids.index(second_id) < ids.index(first_id)

    def test_list_subscriptions_order_by_next_delivery_date(self):
        r1 = self._create_subscription(title="Later delivery")
        r2 = self._create_subscription(title="Earlier delivery")
        assert r1.status_code == status.HTTP_201_CREATED
        assert r2.status_code == status.HTTP_201_CREATED
        first_id = r1.json()["id"]
        second_id = r2.json()["id"]

        Subscription.objects.filter(id=first_id).update(next_delivery_date=datetime(2030, 6, 1, tzinfo=UTC))
        Subscription.objects.filter(id=second_id).update(next_delivery_date=datetime(2030, 1, 1, tzinfo=UTC))

        asc_res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"ordering": "next_delivery_date"})
        assert asc_res.status_code == status.HTTP_200_OK
        asc_ids = [row["id"] for row in asc_res.json()["results"]]
        assert asc_ids.index(second_id) < asc_ids.index(first_id)

        desc_res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"ordering": "-next_delivery_date"})
        assert desc_res.status_code == status.HTTP_200_OK
        desc_ids = [row["id"] for row in desc_res.json()["results"]]
        assert desc_ids.index(first_id) < desc_ids.index(second_id)

    @parameterized.expand(
        [
            ("title",),
            ("-title",),
            ("created_at",),
            ("-created_at",),
            ("created_by__email",),
            ("-created_by__email",),
        ]
    )
    def test_list_subscriptions_accepts_ordering_param(self, ordering):
        res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"ordering": ordering})
        assert res.status_code == status.HTTP_200_OK

    def test_list_subscriptions_search_filters_by_title(self):
        self._create_subscription(title="UniqueSearchableTitle")
        self._create_subscription(title="OtherThing")

        list_res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"search": "UniqueSearchableTitle"})
        assert list_res.status_code == status.HTTP_200_OK
        results = list_res.json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "UniqueSearchableTitle"

    def test_list_subscriptions_filter_by_resource_type(self):
        self.dashboard.tiles.create(insight=self.insight)
        dash_res = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions",
            {
                "dashboard": self.dashboard.id,
                "dashboard_export_insights": [self.insight.id],
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "start_date": "2022-01-01T00:00:00",
                "title": "Dashboard sub",
            },
        )
        assert dash_res.status_code == status.HTTP_201_CREATED
        dash_id = dash_res.json()["id"]

        insight_res = self._create_subscription(title="Insight sub")
        assert insight_res.status_code == status.HTTP_201_CREATED
        insight_id = insight_res.json()["id"]

        only_insight = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"resource_type": "insight"})
        assert only_insight.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in only_insight.json()["results"]}
        assert insight_id in ids
        assert dash_id not in ids

        only_dashboard = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"resource_type": "dashboard"})
        assert only_dashboard.status_code == status.HTTP_200_OK
        ids_d = {r["id"] for r in only_dashboard.json()["results"]}
        assert dash_id in ids_d
        assert insight_id not in ids_d

    def test_list_subscriptions_filter_by_created_by_uuid(self):
        self._create_subscription(title="Mine")
        other_user = self._create_user("other@posthog.com")

        self.client.force_login(other_user)
        self._create_subscription(title="Theirs")

        self.client.force_login(self.user)
        list_res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"created_by": str(self.user.uuid)})
        assert list_res.status_code == status.HTTP_200_OK
        results = list_res.json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Mine"

    @parameterized.expand(
        [
            ("invalid_created_by", "created_by", "not-a-uuid", "created_by"),
            ("invalid_target_type", "target_type", "not_a_channel", "target_type"),
        ],
        name_func=lambda f, _n, p: f"{f.__name__}__{p.args[0]}",
    )
    def test_list_subscriptions_invalid_list_query_param_returns_400(self, _case_label, param, value, expected_attr):
        res = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {param: value})
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json().get("attr") == expected_attr

    def test_list_subscriptions_search_matches_insight_name(self):
        named_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
            name="UniqueInsightNameForSearchTest",
        )
        match_res = self._create_subscription(insight=named_insight.id, title="DifferentTitle")
        assert match_res.status_code == status.HTTP_201_CREATED
        self._create_subscription(title="Noise")

        list_res = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/", {"search": "UniqueInsightNameForSearchTest"}
        )
        assert list_res.status_code == status.HTTP_200_OK
        results = list_res.json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "DifferentTitle"

    @parameterized.expand(
        [("slack",), ("webhook",), ("email",)],
        name_func=lambda f, _n, p: f"{f.__name__}__{p.args[0]}",
    )
    def test_list_subscriptions_filter_by_target_type(self, target_type):
        if target_type == "slack":
            self._create_subscription(title="Email sub")
            slack_integration = Integration.objects.create(team=self.team, kind="slack", config={})
            create_res = self._create_subscription(
                title="Slack sub",
                target_type="slack",
                target_value="C1234|#general",
                integration_id=slack_integration.id,
            )
        elif target_type == "webhook":
            create_res = self._create_subscription(
                title="Webhook sub",
                target_type="webhook",
                target_value="https://example.com/hook",
            )
        else:
            create_res = self._create_subscription(title="Email only sub")
        assert create_res.status_code == status.HTTP_201_CREATED
        sub_id = create_res.json()["id"]

        filtered = self.client.get(f"/api/projects/{self.team.id}/subscriptions/", {"target_type": target_type})
        assert filtered.status_code == status.HTTP_200_OK
        results = filtered.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == sub_id
        assert results[0]["target_type"] == target_type


class TestSubscriptionDeliveryAPI(APILicensedTest):
    subscription: Subscription = None  # type: ignore
    insight: Insight = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.insight = Insight.objects.create(
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )
        cls.subscription = Subscription.objects.create(
            team=cls.team,
            insight=cls.insight,
            created_by=cls.user,
            target_type="email",
            target_value="test@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2022, 1, 1, 0, 0, 0, tzinfo=UTC),
            title="Test Sub",
        )

    def _create_delivery(self, **kwargs):
        params = {
            "subscription": self.subscription,
            "team": self.team,
            "temporal_workflow_id": f"wf-{kwargs.get('idempotency_key', 'default')}",
            "idempotency_key": "default-key",
            "trigger_type": "scheduled",
            "target_type": "email",
            "target_value": "test@posthog.com",
            "status": SubscriptionDelivery.Status.COMPLETED,
        }
        params.update(kwargs)
        return SubscriptionDelivery.objects.create(**params)

    def test_can_list_deliveries(self):
        d1 = self._create_delivery(idempotency_key="key-1")
        d2 = self._create_delivery(idempotency_key="key-2")

        response = self.client.get(f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert ids == {str(d1.id), str(d2.id)}

    def test_can_retrieve_single_delivery(self):
        delivery = self._create_delivery(
            idempotency_key="retrieve-key",
            recipient_results=[{"recipient": "test@posthog.com", "status": "success"}],
            content_snapshot={
                "dashboard": None,
                "insights": [{"id": 1, "name": "Test", "short_id": "abc"}],
                "total_insight_count": 1,
            },
            error={"message": "something failed", "type": "RuntimeError"},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/{delivery.id}/"
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(delivery.id)
        assert data["status"] == "completed"
        assert data["recipient_results"] == [{"recipient": "test@posthog.com", "status": "success"}]
        assert data["error"]["message"] == "something failed"
        assert data["content_snapshot"]["insights"][0]["name"] == "Test"

    def test_deliveries_are_read_only(self):
        delivery = self._create_delivery(idempotency_key="readonly-key")

        response = self.client.post(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/",
            {"status": "failed"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        response = self.client.patch(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/{delivery.id}/",
            {"status": "failed"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_deliveries_scoped_to_subscription(self):
        other_subscription = Subscription.objects.create(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="email",
            target_value="other@posthog.com",
            frequency="daily",
            interval=1,
            start_date=datetime(2022, 1, 1, 0, 0, 0, tzinfo=UTC),
            title="Other Sub",
        )
        self._create_delivery(idempotency_key="this-sub")
        self._create_delivery(
            idempotency_key="other-sub",
            subscription=other_subscription,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["subscription"] == self.subscription.id

    def test_deliveries_ordered_by_created_at_desc(self):
        d1 = self._create_delivery(idempotency_key="older")
        d2 = self._create_delivery(idempotency_key="newer")

        response = self.client.get(f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/")
        results = response.json()["results"]
        assert results[0]["id"] == str(d2.id)
        assert results[1]["id"] == str(d1.id)

    @parameterized.expand(
        [(s,) for s in SubscriptionDelivery.Status],
        name_func=lambda f, _n, p: f"{f.__name__}__{p.args[0].value}",
    )
    def test_deliveries_filter_by_status(self, filter_status):
        other_status = next(s for s in SubscriptionDelivery.Status if s != filter_status)
        self._create_delivery(idempotency_key=f"other-{other_status.value}", status=other_status)
        self._create_delivery(idempotency_key=f"match-{filter_status.value}", status=filter_status)

        base = f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/"
        response = self.client.get(base, {"status": filter_status})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == filter_status

    def test_deliveries_invalid_status_filter_returns_400(self):
        self._create_delivery(idempotency_key="any")
        response = self.client.get(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/",
            {"status": "not-a-status"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.skip_on_multitenancy
    def test_deliveries_require_premium_feature(self):
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get(f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED

    def test_deliveries_not_available_on_legacy_project_path(self):
        self._create_delivery(idempotency_key="legacy-test")
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_delivery_not_found_when_row_belongs_to_different_subscription(self):
        other = Subscription.objects.create(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="email",
            target_value="other@posthog.com",
            frequency="daily",
            interval=1,
            start_date=datetime(2022, 1, 1, 0, 0, 0, tzinfo=UTC),
            title="Other",
        )
        delivery_on_other = self._create_delivery(
            idempotency_key="other-sub-delivery",
            subscription=other,
        )
        response = self.client.get(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/{delivery_on_other.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_delivery_not_found_for_unknown_primary_key(self):
        unknown_id = uuid4()
        while SubscriptionDelivery.objects.filter(pk=unknown_id).exists():
            unknown_id = uuid4()
        response = self.client.get(
            f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/{unknown_id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("ee.api.subscription.SubscriptionDeliveryCursorPagination.page_size", 2)
    def test_deliveries_list_cursor_pagination(self):
        self._create_delivery(idempotency_key="page-a")
        self._create_delivery(idempotency_key="page-b")
        self._create_delivery(idempotency_key="page-c")

        base = f"/api/environments/{self.team.id}/subscriptions/{self.subscription.id}/deliveries/"
        first = self.client.get(base)
        assert first.status_code == status.HTTP_200_OK
        body = first.json()
        assert len(body["results"]) == 2
        assert body["previous"] is None
        assert body["next"] is not None

        second = self.client.get(body["next"])
        assert second.status_code == status.HTTP_200_OK
        body2 = second.json()
        assert len(body2["results"]) == 1
        assert body2["next"] is None

        first_ids = {row["id"] for row in body["results"]}
        second_ids = {row["id"] for row in body2["results"]}
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == {
            str(d.id) for d in SubscriptionDelivery.objects.filter(subscription=self.subscription)
        }
