from rest_framework import status

from posthog.models import Dashboard, OrganizationMembership, User

from ee.api.test.base import APILicensedTest
from ee.models.dashboard_privilege import DashboardPrivilege


class TestDashboardCollaboratorsAPI(APILicensedTest):
    test_dashboard: Dashboard

    def setUp(self):
        super().setUp()
        self.test_dashboard = Dashboard.objects.create(team=self.team, name="Test Insights 9001", created_by=self.user)

    def test_list_collaborators_as_person_without_edit_access(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.created_by = None
        self.test_dashboard.save()
        other_user_a = User.objects.create_and_join(self.organization, "a@x.com", None)
        other_user_b = User.objects.create_and_join(self.organization, "b@x.com", None)
        DashboardPrivilege.objects.create(
            user=other_user_a,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_VIEW,
        )
        DashboardPrivilege.objects.create(
            user=other_user_b,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        response = self.client.get(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        response_data = sorted(response_data, key=lambda entry: entry["user"]["email"])

        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data[0]["user"]["email"], other_user_a.email)
        self.assertEqual(response_data[0]["level"], Dashboard.PrivilegeLevel.CAN_VIEW)
        self.assertEqual(response_data[1]["user"]["email"], other_user_b.email)
        self.assertEqual(response_data[1]["level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_cannot_add_collaborator_to_unrestricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(other_user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data,
            self.validation_error_response("Cannot add collaborators to a dashboard on the lowest restriction level."),
        )

    def test_can_add_collaborator_to_edit_restricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(other_user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response_data["dashboard_id"], self.test_dashboard.id)
        self.assertEqual(response_data["user"]["email"], other_user.email)
        self.assertEqual(response_data["level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_cannot_add_yourself_to_restricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.save()

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(self.user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data,
            self.validation_error_response(
                "Cannot add collaborators that already have inherent access (the dashboard owner or a project admins)."
            ),
        )

    def test_cannot_add_collaborator_to_edit_restricted_dashboard_as_other_user(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.created_by = None
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(other_user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You don't have edit permissions for this dashboard."),
        )

    def test_cannot_add_collaborator_from_other_org_to_edit_restricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.save()
        _, _, other_user = User.objects.bootstrap("Beta", "a@x.com", None)

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(other_user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data,
            self.validation_error_response("Cannot add collaborators that have no access to the project."),
        )

    def test_cannot_add_collaborator_to_other_org_to_edit_restricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.save()
        self.organization_membership.delete()
        _, _, other_user = User.objects.bootstrap("Beta", "a@x.com", None)

        response = self.client.post(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/",
            {
                "user_uuid": str(other_user.uuid),
                "level": Dashboard.PrivilegeLevel.CAN_EDIT,
            },
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You don't have access to the project."),
        )

    def test_cannot_update_existing_collaborator(self):
        # This will change once there are more levels, but with just two it doesn't make sense to PATCH privileges
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        DashboardPrivilege.objects.create(
            user=other_user,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/{other_user.uuid}",
            {"level": Dashboard.PrivilegeLevel.CAN_VIEW},
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_cannot_remove_collaborator_from_unrestricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        DashboardPrivilege.objects.create(
            user=other_user,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        response = self.client.delete(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/{other_user.uuid}"
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data,
            self.validation_error_response(
                "Cannot remove collaborators from a dashboard on the lowest restriction level."
            ),
        )

    def test_can_remove_collaborator_from_restricted_dashboard_as_creator(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        DashboardPrivilege.objects.create(
            user=other_user,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        response = self.client.delete(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/{other_user.uuid}"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_remove_collaborator_from_restricted_dashboard_as_other_user(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.test_dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.test_dashboard.created_by = None
        self.test_dashboard.save()
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        DashboardPrivilege.objects.create(
            user=other_user,
            dashboard=self.test_dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        response = self.client.delete(
            f"/api/projects/{self.test_dashboard.team_id}/dashboards/{self.test_dashboard.id}/collaborators/{other_user.uuid}"
        )
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You don't have edit permissions for this dashboard."),
        )
