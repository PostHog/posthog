from ee.api.test.base import APILicensedTest
from ee.models.organization_resource_access import OrganizationResourceAccess
from ee.models.role import Role, RoleMembership
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import OrganizationMembership


class TestFeatureFlagEnterpriseAPI(APILicensedTest):
    def test_adding_role_edit_access_is_not_restrictive(self):
        FeatureFlag.objects.create(created_by=self.user, key="flag_a", name="Flag A", team=self.team)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.MEMBER)
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
            organization=self.organization,
        )
        role = Role.objects.create(
            name="Marketing",
            organization=self.organization,
            feature_flags_access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
        )
        RoleMembership.objects.create(role=role, user=self.user)
        flag_res = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(flag_res.json()["count"], 1)
        self.assertEqual(flag_res.json()["results"][0]["can_edit"], True)
