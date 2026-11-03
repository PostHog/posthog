from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.test.insight_alerts import create_insight_alert


class TestAlertTakeOwnership(APIBaseTest):
    def _disabled_alert_of_a_former_member(self) -> AlertConfiguration:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        return create_insight_alert(self.team, created_by=former_member, enabled=False)

    def test_enabling_is_rejected_when_the_owner_left(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert.id}", {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == "enabled"
        # The frontend keys its "take ownership" offer, and the cause it shows, on this code.
        assert response.json()["code"] == "owner_left_organization"
        assert (
            "its creator, former-member@example.com, who is no longer in the organization" in response.json()["detail"]
        )

    @parameterized.expand([(False,), (True,)])
    def test_take_ownership_enables_the_alert(self, another_member: bool) -> None:
        alert = self._disabled_alert_of_a_former_member()
        owner = self.user
        if another_member:
            owner = User.objects.create_user(email="new-owner@example.com", first_name="New owner", password=None)
            OrganizationMembership.objects.create(organization=self.organization, user=owner)
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/",
            {"user_uuid": str(owner.uuid)} if another_member else {},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.created_by == owner
        assert alert.enabled is True
        # created_by is excluded from the save diff, so the takeover logs its own activity.
        takeover = ActivityLog.objects.get(scope="AlertConfiguration", item_id=str(alert.id), activity="took_ownership")
        assert takeover.detail is not None
        assert [change["field"] for change in takeover.detail["changes"]] == ["created_by"]
        assert takeover.user == self.user

    @parameterized.expand([("non_admin", 403), ("non_member", 400), ("inactive", 400), ("no_project_access", 400)])
    def test_transfer_ownership_rejects_ineligible_owner(self, reason: str, expected_status: int) -> None:
        alert = self._disabled_alert_of_a_former_member()
        previous_owner = alert.created_by
        owner = User.objects.create_user(
            email="new-owner@example.com", first_name="New owner", password=None, is_active=reason != "inactive"
        )
        if reason != "non_member":
            OrganizationMembership.objects.create(organization=self.organization, user=owner)
        self.organization_membership.level = (
            OrganizationMembership.Level.MEMBER if reason == "non_admin" else OrganizationMembership.Level.ADMIN
        )
        self.organization_membership.save()
        if reason == "no_project_access":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/",
            {"user_uuid": str(owner.uuid)},
        )

        assert response.status_code == expected_status, response.content
        alert.refresh_from_db()
        assert alert.created_by == previous_owner
        assert alert.enabled is False

    def test_take_ownership_is_not_blocked_by_the_alert_limit(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        with patch.object(AlertConfiguration, "check_alert_limit", return_value="Your team has reached the limit."):
            response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/")

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_take_ownership_of_an_ai_alert_needs_the_rollout(self) -> None:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        # Enabled, so the enable path's admission does not run and only the takeover check applies.
        alert = create_insight_alert(self.team, created_by=former_member, enabled=True, detector_config={"type": "llm"})

        with patch("products.alerts.backend.llm_detector_limits.posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take_ownership/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        alert.refresh_from_db()
        assert alert.created_by == former_member
