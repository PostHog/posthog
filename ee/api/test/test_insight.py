import datetime
from datetime import timedelta
from typing import Optional, cast

import time_machine

from django.test import override_settings

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

from ee.api.test.base import APILicensedTest


class TestInsightEnterpriseAPI(APILicensedTest):
    CONFIG_FORCE_ACCESS_CONTROL_ON_SETUP = True

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _require_access_control(self) -> None:
        if not self.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            self.skipTest("This insight RBAC test requires access control")

    def _set_project_default_member_access(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_add_and_remove_tags(self) -> None:
        with time_machine.travel("2012-01-14T03:21:34.000Z", tick=False):
            insight_id, response_data = self.dashboard_api.create_insight({"name": "a created dashboard"})
        insight_short_id = response_data["short_id"]
        self.assertEqual(response_data["tags"], [])

        with time_machine.travel("2012-01-14T03:21:35.000Z", tick=False):
            add_tags_response = self.client.patch(
                # tags are displayed in order of insertion
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"tags": ["2", "1", "3"]},
            )

        self.assertEqual(sorted(add_tags_response.json()["tags"]), ["1", "2", "3"])

        with time_machine.travel("2012-01-14T03:21:36.000Z", tick=False):
            remove_tags_response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"tags": ["3"]}
            )

        self.assertEqual(remove_tags_response.json()["tags"], ["3"])

        self.assert_insight_activity(
            insight_id=insight_id,
            expected=[
                {
                    "activity": "updated",
                    "created_at": "2012-01-14T03:21:36Z",
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": ["3"],
                                "before": ["1", "2", "3"],
                                "field": "tags",
                                "type": "Insight",
                            }
                        ],
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "updated",
                    "created_at": "2012-01-14T03:21:35Z",
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": ["1", "2", "3"],
                                "before": [],
                                "field": "tags",
                                "type": "Insight",
                            }
                        ],
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "detail": {
                        "changes": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ],
        )

    def test_update_insight_can_include_tags_when_licensed(self) -> None:
        with time_machine.travel("2012-01-14T03:21:34.000Z", tick=False) as frozen_time:
            insight_id, insight = self.dashboard_api.create_insight({"name": "insight name"})
            short_id = insight["short_id"]

            frozen_time.shift(timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"name": "insight new name", "tags": ["add", "these", "tags"]},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], "insight new name")
            self.assertEqual(sorted(response_data["tags"]), sorted(["add", "these", "tags"]))
            self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}")

            self.assertEqual(response.json()["name"], "insight new name")

            self.assert_insight_activity(
                insight_id,
                [
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "updated",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": [
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "tags",
                                    "before": [],
                                    "after": ["add", "tags", "these"],
                                },
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "name",
                                    "before": "insight name",
                                    "after": "insight new name",
                                },
                            ],
                            "trigger": None,
                            "type": None,
                            "name": "insight new name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:31:34Z",
                    },
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "created",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": None,
                            "trigger": None,
                            "type": None,
                            "name": "insight name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:21:34Z",
                    },
                ],
            )

    def test_cannot_update_an_insight_the_caller_can_only_view(self):
        self._require_access_control()
        self._set_project_default_member_access()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # The caller is not the creator, so the creator bypass does not grant edit access.
        insight: Insight = Insight.objects.create(team=self.team, name="XYZ", created_by=None)
        AccessControl.objects.create(
            team=self.team,
            resource="insight",
            resource_id=str(insight.id),
            access_level="viewer",
            organization_member=self.organization_membership,
            role=None,
        )

        response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight.id}", {"name": "ABC"})
        response_data = response.json()
        insight.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You do not have editor access to this resource."),
        )
        self.assertEqual(insight.name, "XYZ")

    def test_event_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard")
        insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}",
            {"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_searching_insights_includes_tags_and_description(self) -> None:
        insight_one_id, _ = self.dashboard_api.create_insight({"name": "needle in a haystack"})
        insight_two_id, _ = self.dashboard_api.create_insight({"name": "not matching"})

        insight_three_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "tags": ["needle"],
            }
        )

        insight_four_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "description": "another needle",
                "tags": ["not matching"],
            }
        )

        matching = self.client.get(f"/api/projects/{self.team.id}/insights/?search=needle")
        self.assertEqual(matching.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in matching.json()["results"]]
        assert sorted(matched_insights) == [
            insight_one_id,
            insight_three_id,
            insight_four_id,
        ]

    def test_non_admin_user_cannot_add_an_insight_to_a_restricted_dashboard(
        self,
    ) -> None:
        self._require_access_control()
        self._set_project_default_member_access()
        dashboard_restricted = Dashboard.objects.create(team=self.team, created_by=self.user)
        dashboard_restricted_id = dashboard_restricted.id

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        # a member explicitly denied dashboard access cannot add an insight to it
        user_without_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="no_access_user@posthog.com",
            password=None,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard_restricted_id),
            access_level="none",
            organization_member=user_without_permissions.organization_memberships.first(),
        )
        self.client.force_login(user_without_permissions)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_non_admin_user_cannot_create_an_insight_on_a_restricted_dashboard(
        self,
    ) -> None:
        self._require_access_control()
        self._set_project_default_member_access()
        dashboard_restricted = Dashboard.objects.create(team=self.team, created_by=self.user)
        dashboard_restricted_id = dashboard_restricted.id

        user_without_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="no_access_user@posthog.com",
            password=None,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard_restricted_id),
            access_level="none",
            organization_member=user_without_permissions.organization_memberships.first(),
        )
        self.client.force_login(user_without_permissions)

        self.dashboard_api.create_insight(
            data={"name": "blocked on create", "dashboards": [dashboard_restricted_id]},
            expected_status=status.HTTP_403_FORBIDDEN,
        )
        assert not DashboardTile.objects.filter(dashboard_id=dashboard_restricted_id).exists()
        # the rejected request must not leave an orphaned insight behind
        assert not Insight.objects.filter(created_by=user_without_permissions).exists()

    def test_non_admin_user_cannot_remove_an_insight_from_a_restricted_dashboard(
        self,
    ) -> None:
        self._require_access_control()
        self._set_project_default_member_access()
        # create a dashboard the default user can edit
        dashboard_restricted = Dashboard.objects.create(team=self.team, created_by=self.user)
        dashboard_restricted_id = dashboard_restricted.id

        # create an insight on that dashboard
        insight_id, _ = self.dashboard_api.create_insight(
            data={"name": "on restricted dashboard", "dashboards": [dashboard_restricted_id]}
        )

        # a member explicitly denied dashboard access cannot remove the insight from it
        user_without_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="no_remove_access_user@posthog.com",
            password=None,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard_restricted_id),
            access_level="none",
            organization_member=user_without_permissions.organization_memberships.first(),
        )
        self.client.force_login(user_without_permissions)

        # attempting to remove the insight from the dashboard should fail
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": []},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # original user can remove the insight from the dashboard
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": []},
        )
        assert response.status_code == status.HTTP_200_OK

    def assert_insight_activity(self, insight_id: Optional[int], expected: list[dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: list[dict] = activity_response["results"]
        for item in activity:
            item.pop("id", None)
            for envelope_key in ("is_system", "was_impersonated", "client"):
                item.pop(envelope_key, None)

        self.maxDiff = None
        assert activity == expected
