from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret


class ProjectSecretAPIKeysAdminTestBase(APIBaseTest):
    """Base class for tests that require organization admin permissions."""

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()


class TestProjectSecretAPIKeysAPI(ProjectSecretAPIKeysAdminTestBase):
    def test_create_project_secret_api_key(self):
        label = "Test project key"
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": label, "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        data = response.json()

        key = ProjectSecretAPIKey.objects.get(id=data["id"])

        self.assertEqual(
            data,
            {
                "id": str(key.id),
                "label": label,
                "created_at": data["created_at"],
                "scopes": ["endpoint:read"],
                "value": data["value"],
            },
        )
        self.assertTrue(data["value"].startswith("phs_"))

    def test_create_too_many_project_api_keys(self):
        for i in range(0, 10):
            self.client.post(
                f"/api/projects/{self.team.id}/project_secret_api_keys",
                {"label": f"key-{i}", "scopes": ["endpoint:read"]},
            )
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "key-11", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at most 10", response.json()["detail"])

    def test_create_project_api_key_label_required(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys/",
            {"label": "", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn("label", str(data).lower())

    def test_create_project_api_key_scopes_required(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys/",
            {"label": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn("scopes", str(data).lower())

    @parameterized.expand(
        [
            (["endpoint:read"], True),
            (["endpoint:write"], False),
            (["feature_flag:read"], False),
            (["feature_flag:write"], False),
            (["endpoint:read", "endpoint:write"], False),
            (["endpoint:read", "feature_flag:read"], False),
            (["*"], False),
            (["invalid"], False),
            (["endpoint:invalid"], False),
            (["insight:read"], False),
            (["dashboard:read"], False),
        ]
    )
    def test_scope_validation(self, scopes, should_succeed):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "test", "scopes": scopes},
        )
        if should_succeed:
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.json()["scopes"], scopes)
        else:
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("scope", response.json()["detail"].lower())

    def test_wildcard_scope_not_allowed(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "test", "scopes": ["*"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Wildcard scope", response.json()["detail"])

    def test_update_project_api_key(self):
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )
        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "updated-test-label"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(key.id))
        self.assertEqual(data["label"], "updated-test-label")
        self.assertEqual(data["scopes"], ["endpoint:read"])

    def test_delete_project_api_key(self):
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 1)
        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 0)

    def test_list_only_team_project_api_keys(self):
        my_label = "Test"
        my_key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=my_label,
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        ProjectSecretAPIKey.objects.create(
            team=other_team,
            label="Other test",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.assertEqual(ProjectSecretAPIKey.objects.count(), 2)
        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        key_data = response_data[0]

        self.assertEqual(key_data["id"], str(my_key.id))
        self.assertEqual(key_data["label"], my_label)
        self.assertEqual(key_data["mask_value"], my_key.mask_value)
        self.assertEqual(key_data["scopes"], ["endpoint:read"])
        self.assertEqual(key_data["created_by"]["id"], self.user.id)
        self.assertIn("created_at", key_data)

    def test_cannot_access_other_team_api_keys(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_key = ProjectSecretAPIKey.objects.create(
            team=other_team,
            label="Other test",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys/{other_key.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{other_key.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unique_label_per_team(self):
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="duplicate-label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "duplicate-label", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.json()["detail"])

    def test_same_label_different_teams(self):
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="same-label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_user = self._create_user("other@test.com")
        self.organization_membership = other_user.join(organization=other_org, level=OrganizationMembership.Level.ADMIN)

        self.client.force_login(other_user)

        response = self.client.post(
            f"/api/projects/{other_team.id}/project_secret_api_keys",
            {"label": "same-label", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_roll_key(self):
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="same-label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        rolled_key_response = self.client.post(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/roll")
        rolled_key_instance = ProjectSecretAPIKey.objects.get(id=key.id)
        self.assertEqual(rolled_key_response.json()["mask_value"], rolled_key_instance.mask_value)


class TestProjectSecretAPIKeyWithPersonalAPIKey(ProjectSecretAPIKeysAdminTestBase):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.personal_key_value = generate_random_token_personal()
        self.personal_key = PersonalAPIKey.objects.create(
            label="Test Personal Key",
            user=self.user,
            secure_value=hash_key_value(self.personal_key_value),
            scopes=["project:write"],
        )

    def _get_with_personal_key(self, url: str):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.personal_key_value}")

    def _post_with_personal_key(self, url: str, data: dict):
        return self.client.post(url, data, format="json", HTTP_AUTHORIZATION=f"Bearer {self.personal_key_value}")

    def _delete_with_personal_key(self, url: str):
        return self.client.delete(url, HTTP_AUTHORIZATION=f"Bearer {self.personal_key_value}")

    def test_can_create_project_api_key_with_personal_key(self):
        response = self._post_with_personal_key(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Created via personal key", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["label"], "Created via personal key")
        self.assertEqual(data["scopes"], ["endpoint:read"])

    def test_can_list_project_api_keys_with_personal_key(self):
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test Key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        response = self._get_with_personal_key(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

    def test_can_delete_project_api_key_with_personal_key(self):
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test Key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        response = self._delete_with_personal_key(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 0)

    def test_max_limit_enforced_with_personal_key(self):
        for i in range(0, 10):
            ProjectSecretAPIKey.objects.create(
                team=self.team,
                label=f"key-{i}",
                secure_value=hash_key_value(generate_random_token_secret()),
                scopes=["endpoint:read"],
                created_by=self.user,
            )

        response = self._post_with_personal_key(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "key-11", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at most 10", response.json()["detail"])

    def test_personal_key_without_project_write_scope_fails(self):
        self.personal_key.scopes = ["project:read"]
        self.personal_key.save()

        response = self._post_with_personal_key(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Should fail", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestProjectSecretAPIKeyAuthentication(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key_value = generate_random_token_secret()
        self.project_key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test Project Key",
            secure_value=hash_key_value(self.key_value),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

    def _get_with_project_key(self, url: str):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.key_value}")

    def test_cannot_manage_project_keys_with_project_key(self):
        response = self._get_with_project_key(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_create_project_keys_with_project_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Should fail", "scopes": ["endpoint:read"]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_delete_project_keys_with_project_key(self):
        response = self.client.delete(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{self.project_key.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class TestProjectSecretAPIKeyErrorMessages(ProjectSecretAPIKeysAdminTestBase):
    def test_invalid_scope_error_message(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "test", "scopes": ["invalid:scope"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid scope", response.json()["detail"])

    def test_disallowed_scope_error_message(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "test", "scopes": ["insight:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = response.json()["detail"]
        self.assertIn("not available", error_detail)
        self.assertIn("endpoint", error_detail)


class TestProjectSecretAPIKeyPermissions(APIBaseTest):
    """Tests for organization-level permission requirements."""

    def test_member_cannot_create_project_secret_api_key(self):
        """Organization members should not be able to create project secret API keys."""
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Test key", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_update_project_secret_api_key(self):
        """Organization members should not be able to update project secret API keys."""
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Original label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "Updated label"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_delete_project_secret_api_key(self):
        """Organization members should not be able to delete project secret API keys."""
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 1)

    def test_member_can_list_project_secret_api_keys(self):
        """Organization members should be able to list (read) project secret API keys."""
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

    def test_member_can_retrieve_project_secret_api_key(self):
        """Organization members should be able to retrieve (read) a specific project secret API key."""
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["label"], "Test key")

    @parameterized.expand(
        [
            (OrganizationMembership.Level.ADMIN,),
            (OrganizationMembership.Level.OWNER,),
        ]
    )
    def test_admin_and_owner_can_create_project_secret_api_key(self, level):
        """Organization admins and owners should be able to create project secret API keys."""
        self.organization_membership.level = level
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Test key", "scopes": ["endpoint:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            (OrganizationMembership.Level.ADMIN,),
            (OrganizationMembership.Level.OWNER,),
        ]
    )
    def test_admin_and_owner_can_update_project_secret_api_key(self, level):
        """Organization admins and owners should be able to update project secret API keys."""
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Original label",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = level
        self.organization_membership.save()

        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "Updated label"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["label"], "Updated label")

    @parameterized.expand(
        [
            (OrganizationMembership.Level.ADMIN,),
            (OrganizationMembership.Level.OWNER,),
        ]
    )
    def test_admin_and_owner_can_delete_project_secret_api_key(self, level):
        """Organization admins and owners should be able to delete project secret API keys."""
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test key",
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["endpoint:read"],
            created_by=self.user,
        )

        self.organization_membership.level = level
        self.organization_membership.save()

        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 0)
