import datetime
from typing import cast

from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.explicit_team_membership import ExplicitTeamMembership
from ee.models.license import License
from posthog.models import OrganizationMembership
from posthog.models.dashboard import Dashboard
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User


class TestDashboardEnterpriseAPI(APILicensedTest):
    def test_retrieve_dashboard_forbidden_for_project_outsider(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_dashboard_forbidden_for_org_admin(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_dashboard_allowed_for_project_member(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(team=self.team, parent_membership=self.organization_membership)
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_shared_dashboard_in_private_project(self):
        self.team.access_control = True
        self.team.save()
        self.client.logout()
        dashboard = Dashboard.objects.create(team=self.team, name="public dashboard")
        SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, access_token="testtoken", enabled=True)
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_can_set_dashboard_to_restrict_editing_as_creator_who_is_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
            },
            response_data,
        )

    def test_can_set_dashboard_to_restrict_editing_as_creator_who_is_project_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
            },
            response_data,
        )

    def test_cannot_set_dashboard_to_restrict_editing_as_other_user_who_is_project_member(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=creator)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {
                "restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response(
                "Only the dashboard owner and project admins have the restriction rights required to change the dashboard's restriction level."
            ),
        )

    def test_can_set_dashboard_to_restrict_editing_as_other_user_who_is_project_admin(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=creator)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
            },
            response_data,
        )

    def test_can_edit_restricted_dashboard_as_creator_who_is_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Edit-restricted dashboard",
            created_by=self.user,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "Gentle Antelope"},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "name": "Gentle Antelope",
                "effective_restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_privilege_level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
            response_data,
        )

    def test_cannot_edit_restricted_dashboard_as_other_user_who_is_project_member(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Edit-restricted dashboard",
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "Gentle Antelope"},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You don't have edit permissions for this dashboard."),
        )

    def test_can_edit_restricted_dashboard_as_other_user_who_is_project_admin(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Edit-restricted dashboard",
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "Gentle Antelope"},
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset({"name": "Gentle Antelope"}, response_data)

    def test_dashboard_restrictions_have_no_effect_without_license(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Edit-restricted dashboard",
            created_by=self.user,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        License.objects.all().delete()
        self.organization.update_available_product_features()
        self.organization.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictContainsSubset(
            {
                "restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
                "effective_restriction_level": Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
            },
            response_data,
        )

    def test_dashboard_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_sharing_edits_limited_to_collaborators(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="example dashboard",
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing",
            {"enabled": True},
        )

        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You don't have edit permissions for this dashboard."),
        )

    def test_can_edit_dashboard_description_when_collaboration_not_available(self):
        """
        Team collaboration feature is only available on some plans, but if the feature is
        not available, the user should still be able to read/write for migration purposes.
        The access to the feature is blocked in the UI, so this is unlikely to be truly abused.
        """
        self.client.logout()

        self.organization.available_product_features = []
        self.organization.save()
        self.team.access_control = True
        self.team.save()

        user_without_collaboration = User.objects.create_and_join(
            self.organization, "no-collaboration-feature@posthog.com", None
        )
        self.client.force_login(user_without_collaboration)

        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team,
            name="example dashboard",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {
                "description": "i should be allowed to edit this",
                "name": "as well as this",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.description, "i should be allowed to edit this")
        self.assertEqual(dashboard.name, "as well as this")
