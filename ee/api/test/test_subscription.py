from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.subscription import Subscription, SubscriptionDelivery
from posthog.models.utils import generate_random_token_personal, hash_key_value
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
            "enabled": True,
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

    def test_patch_enabled_true_rejected_when_slack_integration_missing(self):
        """Re-enabling a disabled Slack subscription whose integration is gone must be
        rejected up front — otherwise the next delivery would auto-disable it again
        and the user would receive a confusing email seconds after hitting "Enable".
        """
        integration = Integration.objects.create(team=self.team, kind="slack", config={})
        create_response = self._create_subscription(
            target_type="slack",
            target_value="C1234|#general",
            integration_id=integration.id,
        )
        assert create_response.status_code == status.HTTP_201_CREATED
        subscription_id = create_response.json()["id"]

        # Auto-disable: clear integration and disable the subscription
        Subscription.objects.filter(pk=subscription_id).update(enabled=False, integration=None)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "enabled"
        assert "Reconnect Slack" in response.json()["detail"]

    def test_patch_enabled_true_rejected_for_webhook_subscription(self):
        """Webhook delivery is not supported, so a webhook subscription auto-disables on
        first delivery. Re-enabling without changing target_type would just trigger the
        auto-disable path again — surface the precondition failure up front.
        """
        # Webhook subs can be created (target_type is in the model enum) but are
        # auto-disabled by the activity since `webhook` isn't in SUPPORTED_TARGET_TYPES.
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="webhook",
            target_value="https://example.com/hook",
            frequency="daily",
            start_date=timezone.now(),
            insight=self.insight,
            title="webhook sub",
            enabled=False,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "enabled"
        assert "this delivery channel is not currently supported" in response.json()["detail"]

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

    def test_can_set_prompt_guide_when_feature_flag_enabled(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with patch("ee.api.subscription.posthoganalytics.feature_enabled", return_value=True):
            response = self._create_subscription(summary_enabled=True, summary_prompt_guide="focus on revenue trends")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["summary_prompt_guide"] == "focus on revenue trends"

    @parameterized.expand(
        [
            # (case_name, flag_value_during_patch, payload, expected_status, expected_fragment_or_stored_value)
            (
                "reject_non_empty_patch",
                False,
                {"summary_prompt_guide": "changed"},
                status.HTTP_403_FORBIDDEN,
                "AI summary context",
            ),
            ("allow_clear_via_empty_string", False, {"summary_prompt_guide": ""}, status.HTTP_200_OK, ""),
            ("allow_unrelated_patch", False, {"title": "Updated title"}, status.HTTP_200_OK, "original"),
            (
                "allow_non_empty_patch_when_flag_on",
                True,
                {"summary_prompt_guide": "changed"},
                status.HTTP_200_OK,
                "changed",
            ),
            (
                "deny_on_feature_flag_eval_error",
                None,
                {"summary_prompt_guide": "changed"},
                status.HTTP_403_FORBIDDEN,
                "AI summary context",
            ),
        ]
    )
    def test_prompt_guide_patch_behaviour(
        self, case_name: str, flag_value: Optional[bool], payload: dict, expected_status: int, expected_body_fragment
    ):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        with patch("ee.api.subscription.posthoganalytics.feature_enabled", return_value=True):
            create_response = self._create_subscription(summary_enabled=True, summary_prompt_guide="original")
        subscription_id = create_response.json()["id"]

        with patch("ee.api.subscription.posthoganalytics.feature_enabled", return_value=flag_value):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{subscription_id}",
                payload,
            )

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert expected_body_fragment in response.json()["detail"]
        else:
            # Read-back the stored `summary_prompt_guide` on the updated subscription.
            if "summary_prompt_guide" in payload:
                assert response.json()["summary_prompt_guide"] == (expected_body_fragment or "")
            else:
                # Unrelated PATCH — original stored value must survive untouched.
                assert response.json()["summary_prompt_guide"] == expected_body_fragment

    def test_cannot_create_subscription_with_prompt_guide_when_feature_flag_disabled(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with patch("ee.api.subscription.posthoganalytics.feature_enabled", return_value=False):
            response = self._create_subscription(summary_enabled=True, summary_prompt_guide="focus on revenue trends")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI summary context" in response.json()["detail"]

    def _seed_active_summary_subscriptions(self, count: int) -> list[Subscription]:
        # Build raw rows so we can place an org over its tier cap to exercise
        # grandfathering paths without going through the enforced API.
        return [
            Subscription.objects.create(
                team=self.team,
                insight=self.insight,
                target_type="email",
                target_value=f"existing-{i}@posthog.com",
                frequency="weekly",
                interval=1,
                start_date=datetime(2022, 1, 1, tzinfo=UTC),
                title=f"existing {i}",
                created_by=self.user,
                summary_enabled=True,
            )
            for i in range(count)
        ]

    @parameterized.expand(
        [
            ("create_under_limit", 5, 4, status.HTTP_201_CREATED),
            ("create_at_limit", 5, 5, status.HTTP_402_PAYMENT_REQUIRED),
            ("create_over_limit_grandfathered", 5, 7, status.HTTP_402_PAYMENT_REQUIRED),
            ("create_no_limit_configured", None, 1000, status.HTTP_201_CREATED),
        ]
    )
    def test_create_summary_enabled_respects_org_limit(
        self,
        _name: str,
        limit: int | None,
        existing_active: int,
        expected_status: int,
    ) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(existing_active)

        with patch("ee.api.subscription.get_organization_limit", return_value=limit):
            response = self._create_subscription(summary_enabled=True)

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_402_PAYMENT_REQUIRED:
            assert "active AI summaries" in response.json()["detail"]

    def test_patch_transition_to_summary_enabled_blocked_at_limit(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(5)
        # The subscription being patched is currently OFF, so flipping it ON
        # would push the org from 5 -> 6.
        create_response = self._create_subscription(summary_enabled=False)
        sub_id = create_response.json()["id"]

        with patch("ee.api.subscription.get_organization_limit", return_value=5):
            patch_response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{sub_id}",
                {"summary_enabled": True},
            )

        assert patch_response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert "active AI summaries" in patch_response.json()["detail"]

    def test_patch_unrelated_field_on_already_enabled_summary_when_org_over_limit(self) -> None:
        # Grandfathered org with 7 active when the limit is 5 must still be
        # able to edit other fields on those rows. PATCHes that don't change
        # summary_enabled don't re-trigger the cap check.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        existing = self._seed_active_summary_subscriptions(7)

        with patch("ee.api.subscription.get_organization_limit", return_value=5):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{existing[0].id}",
                {"title": "renamed while over the cap"},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "renamed while over the cap"
        assert response.json()["summary_enabled"] is True

    @parameterized.expand(
        [
            ("under_limit", 3, 10, False),
            ("at_limit", 5, 5, True),
        ]
    )
    def test_summary_quota_endpoint(
        self,
        _name: str,
        active_count: int,
        limit: int,
        expected_at_limit: bool,
    ) -> None:
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(active_count)

        with patch("ee.api.subscription.get_organization_limit", return_value=limit):
            response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/summary_quota")

        assert response.status_code == status.HTTP_200_OK, response.content
        payload = response.json()
        assert payload["active_count"] == active_count
        assert payload["limit"] == limit
        assert payload["at_limit"] is expected_at_limit

    def test_summary_quota_endpoint_uses_cache_and_invalidates_on_save(self) -> None:
        # Tight integration check: hot path is the cached read; mutating a
        # subscription via the API busts the cache so the next read reflects
        # the new state without waiting for the TTL.
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(2)

        with patch("ee.api.subscription.get_organization_limit", return_value=10):
            first = self.client.get(f"/api/projects/{self.team.id}/subscriptions/summary_quota")
            assert first.status_code == status.HTTP_200_OK
            assert first.json()["active_count"] == 2

            # New row added directly in DB should NOT be visible — cache hit.
            self._seed_active_summary_subscriptions(1)
            second = self.client.get(f"/api/projects/{self.team.id}/subscriptions/summary_quota")
            assert second.json()["active_count"] == 2

            # Saving via the API path busts the cache.
            self._create_subscription(summary_enabled=True)
            third = self.client.get(f"/api/projects/{self.team.id}/subscriptions/summary_quota")
            # 2 seeded + 1 direct + 1 via API = 4 active.
            assert third.json()["active_count"] == 4

    def test_cap_hit_emits_event_and_dedupes_within_window(self) -> None:
        # Verifies the cap-hit telemetry fires with rich properties on first
        # block and is suppressed on subsequent blocks within the dedupe
        # window so a misbehaving client can't spam the analytics stream.
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(5)

        with (
            patch("ee.api.subscription.get_organization_limit", return_value=5),
            patch("ee.api.subscription.posthoganalytics.capture") as mock_capture,
        ):
            first = self._create_subscription(summary_enabled=True)
            second = self._create_subscription(summary_enabled=True)

        assert first.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert second.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert mock_capture.call_count == 1
        captured_kwargs = mock_capture.call_args.kwargs
        assert captured_kwargs["event"] == "subscription_ai_summary_cap_hit"
        properties = captured_kwargs["properties"]
        assert properties["active_count"] == 5
        assert properties["limit"] == 5
        assert properties["organization_id"] == str(self.organization.id)
        assert properties["is_create"] is True

    def test_restoring_deleted_summary_enabled_subscription_re_checks_cap(self) -> None:
        # An attacker (or a curious user) PATCHing `deleted=False` on a
        # soft-deleted summary_enabled=True subscription must re-trigger the
        # cap — otherwise undeleting can grow the active count past the
        # configured limit without ever flipping summary_enabled.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._seed_active_summary_subscriptions(5)
        deleted_summary = Subscription.objects.create(
            team=self.team,
            insight=self.insight,
            target_type="email",
            target_value="restore@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2022, 1, 1, tzinfo=UTC),
            title="soft-deleted",
            created_by=self.user,
            summary_enabled=True,
            deleted=True,
        )

        with patch("ee.api.subscription.get_organization_limit", return_value=5):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{deleted_summary.id}",
                {"deleted": False},
            )

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert "active AI summaries" in response.json()["detail"]

    def test_grandfathered_toggle_off_succeeds_but_back_on_blocked(self) -> None:
        # Toggling off frees a slot; toggling back on while still at/over the
        # cap is rejected. Together this enforces "you can't grow past the cap".
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        existing = self._seed_active_summary_subscriptions(7)

        with patch("ee.api.subscription.get_organization_limit", return_value=5):
            off_response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{existing[0].id}",
                {"summary_enabled": False},
            )
            on_response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{existing[0].id}",
                {"summary_enabled": True},
            )

        assert off_response.status_code == status.HTTP_200_OK
        assert off_response.json()["summary_enabled"] is False
        assert on_response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert "active AI summaries" in on_response.json()["detail"]

    def test_cap_is_enforced_across_teams_in_the_same_organization(self) -> None:
        # Documents intent: the cap is org-scoped, not team-scoped. Subscriptions
        # spread across multiple teams in the same organization all count toward
        # the same bucket — so a fresh team in a maxed-out org can't add a new
        # summary even if that team has none of its own.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        team_two = Team.objects.create(organization=self.organization, name="Team two")
        team_three = Team.objects.create(organization=self.organization, name="Team three")
        team_three_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=team_three,
            created_by=self.user,
        )

        def _seed_for_team(team: Team, count: int) -> None:
            for i in range(count):
                Subscription.objects.create(
                    team=team,
                    insight=Insight.objects.create(
                        filters=Filter(data=self.insight_filter_dict).to_dict(),
                        team=team,
                        created_by=self.user,
                    ),
                    target_type="email",
                    target_value=f"{team.id}-{i}@posthog.com",
                    frequency="weekly",
                    interval=1,
                    start_date=datetime(2022, 1, 1, tzinfo=UTC),
                    title=f"existing {team.id}/{i}",
                    created_by=self.user,
                    summary_enabled=True,
                )

        _seed_for_team(self.team, 2)
        _seed_for_team(team_two, 2)
        _seed_for_team(team_three, 1)

        with patch("ee.api.subscription.get_organization_limit", return_value=5):
            response = self.client.post(
                f"/api/projects/{team_three.id}/subscriptions",
                {
                    "insight": team_three_insight.id,
                    "target_type": "email",
                    "target_value": "team3-new@posthog.com",
                    "frequency": "weekly",
                    "interval": 1,
                    "start_date": "2022-01-01T00:00:00",
                    "title": "team three's sixth across-org summary",
                    "summary_enabled": True,
                },
            )

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert "active AI summaries" in response.json()["detail"]

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

    def test_deliver_disabled_subscription_returns_409(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = mock_client

        response = self._create_subscription(invite_message=None)
        sub_id = response.json()["id"]
        Subscription.objects.filter(id=sub_id).update(enabled=False)

        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "Re-enable" in response.json()["detail"]

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

    @patch("posthog.rate_limit.SubscriptionTestDeliveryThrottle.rate", new="3/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_test_delivery_throttled_per_team_across_subscriptions_and_keys(self, _rate_limit_enabled_mock):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        self.mock_sync.return_value = mock_client

        throttle_key = f"throttle_subscription_test_delivery_team_{self.team.id}"
        cache.delete(throttle_key)
        self.addCleanup(cache.delete, throttle_key)

        def fresh_api_key_headers() -> dict[str, str]:
            raw_key = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label=f"throttle-{uuid4().hex[:8]}",
                user=self.user,
                secure_value=hash_key_value(raw_key),
                scopes=["*"],
            )
            return {"authorization": f"Bearer {raw_key}"}

        pat_a = fresh_api_key_headers()
        pat_b = fresh_api_key_headers()

        sub_a = self._create_subscription(invite_message=None).json()["id"]
        sub_b = self._create_subscription(invite_message=None).json()["id"]
        mock_client.start_workflow.reset_mock()

        for sub_id, headers in [(sub_a, pat_a), (sub_b, pat_b), (sub_a, pat_b)]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/subscriptions/{sub_id}/test-delivery/",
                headers=headers,
            )
            assert response.status_code == status.HTTP_202_ACCEPTED

        for headers in (pat_a, pat_b):
            response = self.client.post(
                f"/api/projects/{self.team.id}/subscriptions/{sub_b}/test-delivery/",
                headers=headers,
            )
            assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        session_response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/{sub_a}/test-delivery/")
        assert session_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        assert mock_client.start_workflow.call_count == 3

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

    def test_patch_enabled_field(self):
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now(),
            insight=self.insight,
            title="t",
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
            {"enabled": False},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["enabled"] is False
        subscription.refresh_from_db()
        assert subscription.enabled is False

    def test_re_enable_resets_stale_next_delivery_date(self):
        # Without this reset the scheduler's `next_delivery_date__lte=now` filter
        # picks the sub up on its next tick and fires a second delivery right
        # after the immediate TARGET_CHANGE confirmation.
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now(),
            insight=self.insight,
            title="t",
            enabled=False,
        )
        stale_date = timezone.now() - timedelta(days=3)
        Subscription.objects.filter(pk=subscription.pk).update(next_delivery_date=stale_date)

        with patch("ee.api.subscription.sync_connect") as temporal_mock:
            temporal_mock.return_value.start_workflow = AsyncMock()
            response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
                {"enabled": True},
                format="json",
            )

        assert response.status_code == 200, response.content
        subscription.refresh_from_db()
        assert subscription.enabled is True
        assert subscription.next_delivery_date is not None
        assert subscription.next_delivery_date > timezone.now()
        # Re-enable also fires the immediate TARGET_CHANGE confirmation delivery —
        # the date reset prevents the *scheduler* from firing a second one moments later.
        temporal_mock.return_value.start_workflow.assert_called_once()

    @parameterized.expand(
        [
            # `until_date` already in the past → no future occurrence.
            ("until_date_in_past", {"until_date": -1}),
            # `count=2` deliveries already consumed at start_date and start_date+1d.
            ("count_exhausted", {"count": 2}),
        ]
    )
    def test_re_enable_rejects_when_rrule_exhausted(self, _label, schedule_kwargs):
        # Both exhaustion modes land `next_delivery_date=None` via
        # `set_next_delivery_date()`, the scheduler `__lte=now` filter excludes
        # nulls, and the sub would silently never schedule again.
        kwargs = dict(schedule_kwargs)
        if "until_date" in kwargs:
            kwargs["until_date"] = timezone.now() + timedelta(days=kwargs["until_date"])
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now() - timedelta(days=10),
            insight=self.insight,
            title="t",
            enabled=False,
            **kwargs,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
            {"enabled": True},
            format="json",
        )

        assert response.status_code == 400, response.content
        assert "reached its end date" in str(response.json())
        subscription.refresh_from_db()
        assert subscription.enabled is False  # rejected pre-write

    def test_patch_rrule_into_exhausted_state_is_rejected(self):
        # Path 2 of the silent-fail family: editing an active sub's schedule into
        # an exhausted state. `Subscription.save()` would call
        # `set_next_delivery_date()` and land `next_delivery_date=None`.
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now() - timedelta(days=10),
            insight=self.insight,
            title="t",
            enabled=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
            {"until_date": (timezone.now() - timedelta(days=1)).isoformat()},
            format="json",
        )

        assert response.status_code == 400, response.content
        assert "reached its end date" in str(response.json())
        subscription.refresh_from_db()
        assert subscription.next_delivery_date is not None  # unchanged

    def test_create_rejects_when_rrule_already_exhausted(self):
        # Symmetric hole at create-time: a brand-new sub with `until_date` in the
        # past would land `next_delivery_date=None` and silently never schedule.
        response = self._create_subscription(
            start_date="2020-01-01T00:00:00",
            until_date="2020-01-02T00:00:00",
        )
        assert response.status_code == 400, response.content
        assert "reached its end date" in str(response.json())

    def test_re_enable_with_extended_until_date_is_allowed(self):
        # User extending their schedule in the same PATCH that re-enables — the
        # candidate-rrule check honors the new `until_date` and lets it through.
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now() - timedelta(days=10),
            until_date=timezone.now() - timedelta(days=1),
            insight=self.insight,
            title="t",
            enabled=False,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
            {"enabled": True, "until_date": (timezone.now() + timedelta(days=30)).isoformat()},
            format="json",
        )

        assert response.status_code == 200, response.content
        subscription.refresh_from_db()
        assert subscription.enabled is True
        # Scheduler-visible invariant: `next_delivery_date` must be a future timestamp,
        # not None — that's what the candidate-rrule validation defends.
        assert subscription.next_delivery_date is not None
        assert subscription.next_delivery_date > timezone.now()

    def test_get_returns_enabled_field(self):
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now(),
            insight=self.insight,
            title="t",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/")
        assert response.status_code == 200, response.content
        assert response.json()["enabled"] is True

    @parameterized.expand(
        [
            # Locks the workflow-trigger matrix across all four (initial, final) enabled states.
            ("enabled_to_enabled_field_edit", True, {"title": "renamed"}, True),
            ("redundant_enable", True, {"enabled": True}, True),
            ("disable_enabled", True, {"enabled": False}, False),
            ("redundant_disable", False, {"enabled": False}, False),
            ("enable_disabled", False, {"enabled": True}, True),
        ]
    )
    def test_patch_workflow_trigger_for_enabled_field(
        self, _label, initial_enabled, patch_payload, expect_workflow_called
    ):
        subscription = Subscription.objects.create(
            team=self.team,
            target_type="email",
            target_value="vasco@posthog.com",
            frequency="daily",
            start_date=timezone.now(),
            insight=self.insight,
            title="t",
            enabled=initial_enabled,
        )
        with patch("ee.api.subscription.sync_connect") as temporal_mock:
            temporal_mock.return_value.start_workflow = AsyncMock()
            response = self.client.patch(
                f"/api/projects/{self.team.id}/subscriptions/{subscription.id}/",
                patch_payload,
                format="json",
            )
            assert response.status_code == 200, response.content
            if expect_workflow_called:
                temporal_mock.return_value.start_workflow.assert_called_once()
            else:
                temporal_mock.return_value.start_workflow.assert_not_called()


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
