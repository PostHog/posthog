from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership


class TestAccessControlAPI(APILicensedTest):
    # def _create_access_control(
    #     self, resource="project", resource_id=None, access_level="admin", organization_member=None, team=None, role=None
    # ):
    #     return AccessControl.objects.create(
    #         organization=self.organization,
    #         resource=resource,
    #         resource_id=resource_id or self.team.id,
    #         access_level=access_level,
    #         # Targets
    #         organization_member=organization_member,
    #         team=team,
    #         role=role,
    #     )

    def setUp(self):
        super().setUp()
        self.organization.available_features = [
            AvailableFeature.PROJECT_BASED_PERMISSIONING,
            AvailableFeature.ROLE_BASED_ACCESS,
        ]
        self.organization.save()

    def _put_access_control(self, data):
        payload = {
            "resource": "project",
            "resource_id": self.team.id,
            "access_level": "admin",
        }

        payload.update(data)
        return self.client.put(
            "/api/organizations/@current/access_controls",
            payload,
        )

    def _org_membership(self, level: OrganizationMembership.Level = OrganizationMembership.Level.ADMIN):
        self.organization_membership.level = level
        self.organization_membership.save()

    def test_project_change_rejected_if_not_org_admin(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        res = self._put_access_control({"team": self.team.id})
        assert res.status_code == status.HTTP_403_FORBIDDEN, res.json()

    def test_project_change_accepted_if_org_admin(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        res = self._put_access_control({"team": self.team.id})
        assert res.status_code == status.HTTP_200_OK, res.json()

    def test_project_change_if_in_access_control(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        # Add ourselves to access
        res = self._put_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_200_OK, res.json()

        self._org_membership(OrganizationMembership.Level.MEMBER)

        # Now change ourselves to a member
        res = self._put_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "member"}
        )
        assert res.status_code == status.HTTP_200_OK, res.json()
        assert res.json()["access_level"] == "member"

        # Now try and change our own membership and fail!
        res = self._put_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.json()["detail"] == "You must be an admin to modify project permissions."

    def test_project_change_rejected_if_not_in_organization(self):
        self.organization_membership.delete()
        # Add ourselves to access
        res = self._put_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND, res.json()
