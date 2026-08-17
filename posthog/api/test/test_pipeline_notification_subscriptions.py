from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership, User

ADMIN_FLAG = "admin-pipeline-notification-controls"
REALTIME_FLAG = "real-time-notifications"

PIPELINE_A = "hog_function:0198aaaa-1111-4222-8333-444455556666"
PIPELINE_B = "batch_export:0198bbbb-2222-4333-8444-555566667777"
PIPELINE_C = "plugin_config:42"


def _admin_flag_only(flag: str, *args, **kwargs) -> bool:
    return flag == ADMIN_FLAG


def _no_flags(flag: str, *args, **kwargs) -> bool:
    return False


def _admin_and_realtime_flags(flag: str, *args, **kwargs) -> bool:
    return flag in (ADMIN_FLAG, REALTIME_FLAG)


class TestPipelineNotificationSubscriptions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.member = self._create_user("member@posthog.com")
        self.url = f"/api/projects/{self.team.id}/pipeline_notification_subscriptions/"

    def _set_muted(self, user, pipeline_ids: list[str]) -> None:
        user.partial_notification_settings = {"pipeline_notifications_disabled": dict.fromkeys(pipeline_ids, True)}
        user.save()

    def _member_row(self, results: list[dict], email: str) -> dict:
        return next(row for row in results if row["email"] == email)

    def _muted_pipelines(self, user) -> dict:
        user.refresh_from_db()
        return (user.partial_notification_settings or {})["pipeline_notifications_disabled"]

    @parameterized.expand([("list",), ("bulk_update",)])
    @patch("posthoganalytics.feature_enabled", side_effect=_no_flags)
    def test_requires_the_feature_flag(self, action: str, _mock_flag) -> None:
        if action == "list":
            response = self.client.get(self.url)
        else:
            response = self.client.post(
                f"{self.url}bulk_update/",
                {"changes": [{"user_id": self.member.id, "pipeline_id": PIPELINE_A, "subscribed": False}]},
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_requires_organization_admin(self, _mock_flag) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_list_reports_who_receives_failure_emails(self, _mock_flag) -> None:
        self._set_muted(self.member, [PIPELINE_A])

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        row = self._member_row(response.json(), self.member.email)
        assert row["unsubscribed_pipeline_ids"] == [PIPELINE_A]
        assert row["pipeline_emails_enabled"] is True
        assert row["editable"] is True
        assert row["organization_membership_level"] == OrganizationMembership.Level.MEMBER

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_list_reports_a_member_who_turned_all_pipeline_emails_off(self, _mock_flag) -> None:
        self.member.partial_notification_settings = {"plugin_disabled": False}
        self.member.save()

        response = self.client.get(self.url)

        row = self._member_row(response.json(), self.member.email)
        assert row["pipeline_emails_enabled"] is False

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_admin_cannot_change_an_owner(self, _mock_flag) -> None:
        owner = self._create_user("owner@posthog.com", level=OrganizationMembership.Level.OWNER)

        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": owner.id, "pipeline_id": PIPELINE_A, "subscribed": False}]},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        owner.refresh_from_db()
        assert (owner.partial_notification_settings or {}).get("pipeline_notifications_disabled") in (None, {})

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_unsubscribing_leaves_the_members_other_pipelines_alone(self, _mock_flag) -> None:
        self._set_muted(self.member, [PIPELINE_B])

        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": self.member.id, "pipeline_id": PIPELINE_A, "subscribed": False}]},
        )

        assert response.status_code == status.HTTP_200_OK
        assert self._muted_pipelines(self.member) == {PIPELINE_A: True, PIPELINE_B: True}

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_subscribing_clears_only_the_named_pipeline(self, _mock_flag) -> None:
        self._set_muted(self.member, [PIPELINE_A, PIPELINE_B])

        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": self.member.id, "pipeline_id": PIPELINE_B, "subscribed": True}]},
        )

        assert response.status_code == status.HTTP_200_OK
        assert self._muted_pipelines(self.member) == {PIPELINE_A: True}
        row = self._member_row(response.json(), self.member.email)
        assert row["unsubscribed_pipeline_ids"] == [PIPELINE_A]

    @parameterized.expand(
        [
            ("unknown_prefix", "webhook:0198aaaa-1111-4222-8333-444455556666"),
            ("missing_prefix", "0198aaaa-1111-4222-8333-444455556666"),
            ("empty_id", "hog_function:"),
        ]
    )
    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_rejects_an_invalid_pipeline_id(self, _name: str, pipeline_id: str, _mock_flag) -> None:
        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": self.member.id, "pipeline_id": pipeline_id, "subscribed": False}]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthoganalytics.feature_enabled", side_effect=_admin_flag_only)
    def test_rejects_a_user_outside_the_organization(self, _mock_flag) -> None:
        other_organization, _, other_user = User.objects.bootstrap("Other org", "outsider@posthog.com", "password")

        response = self.client.post(
            f"{self.url}bulk_update/",
            {"changes": [{"user_id": other_user.id, "pipeline_id": PIPELINE_A, "subscribed": False}]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert other_organization.members.count() == 1

    @patch("posthog.api.pipeline_notification_subscriptions.create_notification")
    @patch("posthoganalytics.feature_enabled", side_effect=_admin_and_realtime_flags)
    def test_notifies_each_affected_member_once_per_save(self, _mock_flag, mock_create_notification) -> None:
        second_member = self._create_user("second@posthog.com")

        response = self.client.post(
            f"{self.url}bulk_update/",
            {
                "changes": [
                    {"user_id": self.member.id, "pipeline_id": PIPELINE_A, "subscribed": False},
                    {"user_id": self.member.id, "pipeline_id": PIPELINE_B, "subscribed": False},
                    {"user_id": second_member.id, "pipeline_id": PIPELINE_C, "subscribed": False},
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        notified = sorted(call.args[0].target_id for call in mock_create_notification.call_args_list)
        assert notified == sorted([str(self.member.id), str(second_member.id)])
