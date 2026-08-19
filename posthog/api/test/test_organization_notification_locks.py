from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.organization_notification_lock import (
    OrganizationMemberNotificationLock,
    effective_notification_settings,
)
from posthog.tasks.email import should_send_notification

GOVERNANCE_FLAG = "org-notification-governance"


def _governance_flag(flag: str, *args, **kwargs) -> bool:
    return flag == GOVERNANCE_FLAG


def _no_flags(flag: str, *args, **kwargs) -> bool:
    return False


class TestOrganizationNotificationLocks(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "Organization security settings"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.member = self._create_user("member@posthog.com")
        self.url = f"/api/organizations/{self.organization.id}/notification_locks/"

    def _lock(self, user_id: int | None, setting: str, value: bool | None, scope_id: str = "") -> None:
        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": user_id, "setting": setting, "scope_id": scope_id, "locked_value": value}]},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

    @parameterized.expand([("list",), ("bulk_update",)])
    @patch("posthoganalytics.feature_enabled", side_effect=_no_flags)
    def test_requires_the_feature_flag(self, action: str, _mock_flag) -> None:
        if action == "list":
            response = self.client.get(self.url)
        else:
            response = self.client.post(
                f"{self.url}bulk_update/",
                {"changes": [{"user_id": self.member.id, "setting": "plugin_disabled", "locked_value": False}]},
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_requires_the_entitlement(self, _mock_flag) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_requires_organization_admin(self, _mock_flag) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_admin_cannot_lock_an_owner(self, _mock_flag) -> None:
        owner = self._create_user("owner@posthog.com", level=OrganizationMembership.Level.OWNER)

        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": owner.id, "setting": "plugin_disabled", "locked_value": False}]},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert OrganizationMemberNotificationLock.objects.count() == 0

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_rejects_a_setting_that_cannot_be_locked(self, _mock_flag) -> None:
        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": self.member.id, "setting": "project_api_key_exposed", "locked_value": False}]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_lock_overrides_the_members_own_setting_without_changing_it(self, _mock_flag) -> None:
        self.member.partial_notification_settings = {"plugin_disabled": True}
        self.member.save()

        self._lock(self.member.id, "plugin_disabled", False)

        self.member.refresh_from_db()
        assert self.member.partial_notification_settings == {"plugin_disabled": True}
        assert effective_notification_settings(self.member)["plugin_disabled"] is False
        assert should_send_notification(self.member, "plugin_disabled") is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_unlocking_restores_the_members_own_setting(self, _mock_flag) -> None:
        self.member.partial_notification_settings = {"plugin_disabled": True}
        self.member.save()
        self._lock(self.member.id, "plugin_disabled", False)

        self._lock(self.member.id, "plugin_disabled", None)

        assert effective_notification_settings(self.member)["plugin_disabled"] is True

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_an_all_members_lock_covers_someone_who_joins_later(self, _mock_flag) -> None:
        self._lock(None, "plugin_disabled", False)

        joiner = self._create_user("joiner@posthog.com")

        assert effective_notification_settings(joiner)["plugin_disabled"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_member_lock_beats_an_all_members_lock(self, _mock_flag) -> None:
        self._lock(None, "plugin_disabled", False)
        self._lock(self.member.id, "plugin_disabled", True)

        assert effective_notification_settings(self.member)["plugin_disabled"] is True

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_scoped_lock_only_covers_its_own_scope(self, _mock_flag) -> None:
        pipeline = "hog_function:0198aaaa-1111-4222-8333-444455556666"
        other = "hog_function:0198bbbb-2222-4333-8444-555566667777"

        self._lock(self.member.id, "pipeline_notifications_disabled", True, scope_id=pipeline)

        settings = effective_notification_settings(self.member)
        assert settings["pipeline_notifications_disabled"] == {pipeline: True}
        assert other not in settings["pipeline_notifications_disabled"]

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_member_cannot_change_a_locked_setting(self, _mock_flag) -> None:
        self._lock(self.member.id, "plugin_disabled", False)

        self.client.force_login(self.member)
        response = self.client.patch("/api/users/@me/", {"notification_settings": {"plugin_disabled": True}})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert effective_notification_settings(self.member)["plugin_disabled"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_member_can_still_change_an_unlocked_setting(self, _mock_flag) -> None:
        self._lock(self.member.id, "plugin_disabled", False)

        self.client.force_login(self.member)
        response = self.client.patch(
            "/api/users/@me/", {"notification_settings": {"error_tracking_issue_assigned": False}}
        )

        assert response.status_code == status.HTTP_200_OK

    @patch("posthog.api.organization_notification_locks.create_notification")
    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_notifies_each_affected_member_once_per_save(self, _mock_flag, mock_create_notification) -> None:
        second = self._create_user("second@posthog.com")

        response = self.client.post(
            f"{self.url}bulk_update/",
            {
                "changes": [
                    {"user_id": self.member.id, "setting": "plugin_disabled", "locked_value": False},
                    {"user_id": self.member.id, "setting": "all_weekly_digest_disabled", "locked_value": True},
                    {"user_id": second.id, "setting": "plugin_disabled", "locked_value": False},
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        notified = sorted(call.args[0].target_id for call in mock_create_notification.call_args_list)
        assert notified == sorted([str(self.member.id), str(second.id)])
