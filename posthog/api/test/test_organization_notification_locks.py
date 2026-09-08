from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpResponse

from parameterized import parameterized
from rest_framework import status

from posthog.api.organization_notification_locks import MAX_CHANGES_PER_REQUEST
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.organization_notification_lock import (
    OrganizationMemberNotificationLock,
    effective_notification_settings,
)
from posthog.tasks.email import NotificationSetting, get_members_to_notify, should_send_pipeline_error_notification

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

    def _change(self, **kwargs) -> dict:
        return {"user_id": self.member.id, "scope_id": "", "locked_value": True, **kwargs}

    def _post(self, *changes) -> HttpResponse:
        return self.client.post(f"{self.url}bulk_update/", {"changes": list(changes)})

    @parameterized.expand([("list",), ("bulk_update",)])
    @patch("posthoganalytics.feature_enabled", side_effect=_no_flags)
    def test_requires_the_feature_flag(self, action: str, _mock_flag) -> None:
        response = (
            self.client.get(self.url) if action == "list" else self._post(self._change(setting="discussions_mentioned"))
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_requires_the_entitlement(self, _mock_flag) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        assert self.client.get(self.url).status_code == status.HTTP_402_PAYMENT_REQUIRED

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_requires_organization_admin(self, _mock_flag) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_admin_cannot_change_an_owner(self, _mock_flag) -> None:
        owner = self._create_user("owner@posthog.com", level=OrganizationMembership.Level.OWNER)

        response = self._post(self._change(user_id=owner.id, setting="discussions_mentioned"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert OrganizationMemberNotificationLock.objects.count() == 0

    @parameterized.expand(
        [
            ("security_setting", {"setting": "project_api_key_exposed"}),
            ("master_switch", {"setting": "plugin_disabled"}),
            ("scope_on_a_single_switch", {"setting": "discussions_mentioned", "scope_id": "42"}),
            ("missing_scope", {"setting": "project_weekly_digest_disabled"}),
            ("project_of_another_organization", {"setting": "project_weekly_digest_disabled", "scope_id": "99999"}),
            (
                "organization_that_is_not_this_one",
                {
                    "setting": "organization_member_join_email_disabled",
                    "scope_id": "018f0000-0000-4000-8000-000000000000",
                },
            ),
        ]
    )
    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_rejects_an_invalid_rule(self, _name: str, overrides: dict, _mock_flag) -> None:
        assert self._post(self._change(**overrides)).status_code == status.HTTP_400_BAD_REQUEST
        assert OrganizationMemberNotificationLock.objects.count() == 0

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_rule_overrides_the_members_setting_without_changing_it(self, _mock_flag) -> None:
        self.member.partial_notification_settings = {"discussions_mentioned": True}
        self.member.save()

        assert self._post(self._change(setting="discussions_mentioned", locked_value=False)).status_code == 200

        self.member.refresh_from_db()
        assert self.member.partial_notification_settings == {"discussions_mentioned": True}
        assert effective_notification_settings(self.member)["discussions_mentioned"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_removing_a_rule_restores_the_members_setting(self, _mock_flag) -> None:
        self.member.partial_notification_settings = {"discussions_mentioned": True}
        self.member.save()
        self._post(self._change(setting="discussions_mentioned", locked_value=False))

        assert self._post(self._change(setting="discussions_mentioned", locked_value=None)).status_code == 200
        assert effective_notification_settings(self.member)["discussions_mentioned"] is True

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_project_rule_only_covers_its_own_project(self, _mock_flag) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")

        self._post(
            self._change(setting="project_weekly_digest_disabled", scope_id=str(self.team.id), locked_value=True)
        )

        settings = effective_notification_settings(self.member)
        assert settings["project_weekly_digest_disabled"] == {str(self.team.id): True}
        assert str(other.id) not in settings["project_weekly_digest_disabled"]

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_rule_does_not_reach_another_organization(self, _mock_flag) -> None:
        # discussions_mentioned is stored once per user, so without scoping this organization's
        # rule would silence the member everywhere else they work too.
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other org project")
        OrganizationMembership.objects.create(user=self.member, organization=other_org)

        self._post(self._change(setting="discussions_mentioned", locked_value=False))

        assert self.member.id not in [
            m.user_id for m in get_members_to_notify(self.team, NotificationSetting.DISCUSSIONS_MENTIONED.value)
        ]
        assert self.member.id in [
            m.user_id for m in get_members_to_notify(other_team, NotificationSetting.DISCUSSIONS_MENTIONED.value)
        ]

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_project_rule_decides_pipeline_failure_emails(self, _mock_flag) -> None:
        # Stored per pipeline, governed per project, so this path is resolved separately.
        self._post(
            self._change(setting="pipeline_notifications_disabled", scope_id=str(self.team.id), locked_value=True)
        )

        assert should_send_pipeline_error_notification(self.member, team_id=self.team.id) is False
        assert should_send_pipeline_error_notification(self.member, team_id=self.team.id + 5000) is True

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_member_cannot_change_a_setting_a_rule_decides(self, _mock_flag) -> None:
        self._post(self._change(setting="discussions_mentioned", locked_value=False))

        self.client.force_login(self.member)
        response = self.client.patch(
            "/api/users/@me/",
            {"notification_settings": {"discussions_mentioned": False}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.member.refresh_from_db()
        assert self.member.notification_settings["discussions_mentioned"] is True
        assert effective_notification_settings(self.member)["discussions_mentioned"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_a_member_can_still_change_everything_else(self, _mock_flag) -> None:
        self._post(self._change(setting="discussions_mentioned", locked_value=False))

        self.client.force_login(self.member)
        # The settings page submits the whole map, so the governed key rides along at its stored value.
        response = self.client.patch(
            "/api/users/@me/",
            {"notification_settings": {"discussions_mentioned": True, "error_tracking_issue_assigned": False}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        self.member.refresh_from_db()
        assert self.member.notification_settings["error_tracking_issue_assigned"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_one_bad_change_saves_none_of_the_batch(self, _mock_flag) -> None:
        response = self._post(
            self._change(setting="discussions_mentioned"),
            self._change(setting="project_weekly_digest_disabled", scope_id="99999"),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert OrganizationMemberNotificationLock.objects.count() == 0

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_rejects_a_batch_over_the_limit(self, _mock_flag) -> None:
        changes = [self._change(setting="discussions_mentioned")] * (MAX_CHANGES_PER_REQUEST + 1)

        assert self._post(*changes).status_code == status.HTTP_400_BAD_REQUEST
        assert OrganizationMemberNotificationLock.objects.count() == 0

    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_rejects_a_user_outside_the_organization(self, _mock_flag) -> None:
        _, _, outsider = User.objects.bootstrap("Other org", "outsider@posthog.com", "password")

        assert self._post(self._change(user_id=outsider.id, setting="discussions_mentioned")).status_code == 400

    @patch("posthog.api.organization_notification_locks.create_notification")
    @patch("posthoganalytics.feature_enabled", side_effect=_governance_flag)
    def test_notifies_each_affected_member_once_per_save(self, _mock_flag, mock_create_notification) -> None:
        second = self._create_user("second@posthog.com")

        response = self._post(
            self._change(setting="discussions_mentioned"),
            self._change(setting="error_tracking_issue_assigned"),
            self._change(user_id=second.id, setting="discussions_mentioned"),
        )

        assert response.status_code == status.HTTP_200_OK
        notified = sorted(call.args[0].target_id for call in mock_create_notification.call_args_list)
        assert notified == sorted([str(self.member.id), str(second.id)])
