from typing import cast

from django.utils import timezone
from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.models import Dashboard, DashboardTile, Insight, OrganizationMembership, User


class TestInsightEnterpriseAPI(APILicensedTest):
    def test_cannot_update_restricted_insight_as_other_user_who_is_project_member(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        original_name = "Edit-restricted dashboard"
        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team,
            name=original_name,
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        insight: Insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight.id}", {"name": "ABC"})
        response_data = response.json()
        dashboard.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEquals(
            response_data,
            self.permission_denied_response(
                "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."
            ),
        )
        self.assertEqual(dashboard.name, original_name)

    def test_cannot_delete_restricted_insight_as_other_user_who_is_project_member(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Edit-restricted dashboard",
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.delete(f"/api/projects/{self.team.id}/insights/{insight.id}")
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEquals(
            response_data,
            self.permission_denied_response(
                "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."
            ),
        )

    def test_event_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard",)
        insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight.id}", {"tags": ["a", "b", "a"]})

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])
