from ee.api.test.base import APILicensedTest
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from ee.models.rbac.role import Role, RoleMembership
from posthog.models.feature_flag import FeatureFlag
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models import User
from rest_framework import status
from posthog.models.utils import generate_random_token_personal


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


class TestFeatureFlagLocalEvaluation(APILicensedTest):
    def test_local_evaluation_with_valid_personal_api_key(self):
        user = User.objects.create_user(email="testuser@example.com", first_name="Test", password="password")

        OrganizationMembership.objects.create(user=user, organization=self.organization)

        user.current_team_id = self.team.id
        user.save()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
        )
        FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["flags"]), 1)
        self.assertEqual(response.json()["flags"][0]["key"], "beta-feature")
        self.assertEqual(response.json()["group_type_mapping"], {})
        self.assertEqual(response.json()["cohorts"], {})
