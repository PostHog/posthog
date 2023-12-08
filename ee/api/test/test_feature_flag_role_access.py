from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.organization_resource_access import OrganizationResourceAccess
from ee.models.role import Role
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class TestFeatureFlagRoleAccessAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.eng_role = Role.objects.create(name="Engineering", organization=self.organization)
        self.marketing_role = Role.objects.create(name="Marketing", organization=self.organization)
        self.feature_flag = FeatureFlag.objects.create(
            created_by=self.user,
            team=self.team,
            key="flag_role_access",
            name="Flag role access",
        )

    def test_can_always_add_role_access_if_creator_of_feature_flag(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )
        self.assertEqual(self.user.role_memberships.count(), 0)
        flag_role_access_create_res = self.client.post(
            f"/api/projects/@current/feature_flags/{self.feature_flag.id}/role_access",
            {"role_id": self.eng_role.id},
        )
        self.assertEqual(flag_role_access_create_res.status_code, status.HTTP_201_CREATED)
        flag_role = FeatureFlagRoleAccess.objects.get(id=flag_role_access_create_res.json()["id"])
        self.assertEqual(flag_role.role.name, self.eng_role.name)
        self.assertEqual(flag_role.feature_flag.id, self.feature_flag.id)

    def test_role_access_with_deleted_creator_of_feature_flag(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )

        flag = FeatureFlag.objects.create(
            created_by=None,
            team=self.team,
            key="flag_role_access_none",
            name="Flag role access",
        )
        self.assertEqual(self.user.role_memberships.count(), 0)
        flag_role_access_create_res = self.client.post(
            f"/api/projects/@current/feature_flags/{flag.id}/role_access",
            {"role_id": self.eng_role.id},
        )
        self.assertEqual(flag_role_access_create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_add_role_access_if_feature_flags_access_level_too_low_and_not_creator(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )
        self.assertEqual(self.user.role_memberships.count(), 0)
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        flag = FeatureFlag.objects.create(created_by=user_a, key="flag_a", name="Flag A", team=self.team)
        res = self.client.post(
            f"/api/projects/@current/feature_flags/{flag.id}/role_access",
            {"role_id": self.marketing_role.id},
        )
        response_data = res.json()
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response("You can't edit roles for this feature flag."),
        )

    def test_can_add_role_access_if_role_feature_flags_access_level_allows(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.save()
        self.organization_membership.save()
        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": self.user.uuid},
        )
        self.assertEqual(
            self.user.role_memberships.first().role.feature_flags_access_level,  # type: ignore
            OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        )
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        flag = FeatureFlag.objects.create(created_by=user_a, key="flag_a", name="Flag A", team=self.team)
        flag_id = flag.id
        res = self.client.post(
            f"/api/projects/@current/feature_flags/{flag_id}/role_access",
            {"role_id": self.marketing_role.id},
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_feature_flag_permission_changes(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )

        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        flag = FeatureFlag.objects.create(created_by=user_a, key="flag_a", name="Flag A", team=self.team)

        # Should only have viewing privileges
        response_flags = self.client.get(f"/api/projects/@current/feature_flags")
        self.assertEqual(response_flags.json()["results"][0]["can_edit"], False)

        # change to admin so we can mimic someone else adding us to the role and feature flag
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Add role membership and feature flag access level
        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": self.user.uuid},
        )

        self.client.post(
            f"/api/projects/@current/feature_flags/{flag.id}/role_access",
            {"role_id": self.eng_role.id},
        )
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        # Should now have edit privileges
        response_flags = self.client.get(f"/api/projects/@current/feature_flags")
        self.assertEqual(response_flags.json()["results"][0]["can_edit"], True)

    def test_can_always_edit_if_admin_or_higher(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        flag = FeatureFlag.objects.create(created_by=user_a, key="flag_a", name="Flag A", team=self.team)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        res = self.client.post(
            f"/api/projects/@current/feature_flags/{flag.id}/role_access",
            {"role_id": self.eng_role.id},
        )

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/@current/feature_flags/{flag.id}/role_access",
            {"role_id": self.marketing_role.id},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You can't edit roles for this feature flag."),
        )
