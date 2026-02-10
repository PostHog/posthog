from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import NotFound

from posthog.auth import ProjectSecretAPIKeyAuthentication, ProjectSecretAPIKeyUser
from posthog.models import ActivityLog, FeatureFlag
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret
from posthog.permissions import ProjectSecretAPIKeyPermission

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_managed_key(team, user, scopes=None, label="Test Key"):
    key_value = generate_random_token_secret()
    key = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        secure_value=hash_key_value(key_value),
        scopes=scopes or ["feature_flag:read"],
        created_by=user,
    )
    return key, key_value


def _create_feature_flag(team, key="test-flag"):
    return FeatureFlag.objects.create(
        team=team,
        key=key,
        name="Test Flag",
        filters={"groups": [{"rollout_percentage": 100}]},
        active=True,
    )


class _AdminBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()


# ===========================================================================
# 1. CRUD API (management viewset)
# ===========================================================================


class TestProjectSecretAPIKeyCRUD(_AdminBase):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "My key", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data["value"].startswith("phs_"))
        self.assertEqual(data["label"], "My key")
        self.assertEqual(data["scopes"], ["feature_flag:read"])

    def test_list_returns_only_own_team_keys(self):
        _create_managed_key(self.team, self.user, label="mine")

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other")
        _create_managed_key(other_team, self.user, label="theirs")

        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["label"], "mine")

    def test_retrieve(self):
        key, _ = _create_managed_key(self.team, self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(key.id))
        self.assertNotIn("value", response.json())

    def test_update_label(self):
        key, _ = _create_managed_key(self.team, self.user, label="old")
        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "new"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["label"], "new")

    def test_update_with_empty_scopes_rejected(self):
        key, _ = _create_managed_key(self.team, self.user)
        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"scopes": []},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scope", str(response.json()).lower())

    def test_delete(self):
        key, _ = _create_managed_key(self.team, self.user)
        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProjectSecretAPIKey.objects.filter(team=self.team).count(), 0)

    def test_roll_key(self):
        key, old_value = _create_managed_key(self.team, self.user)
        response = self.client.post(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/roll")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["value"].startswith("phs_"))
        self.assertNotEqual(data["value"], old_value)
        self.assertIsNotNone(data["last_rolled_at"])

    def test_max_keys_per_project(self):
        for i in range(10):
            _create_managed_key(self.team, self.user, label=f"key-{i}")
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "overflow", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at most 10", response.json()["detail"])

    def test_unique_label_per_team(self):
        _create_managed_key(self.team, self.user, label="dup")
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "dup", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.json()["detail"])

    def test_same_label_across_teams_ok(self):
        _create_managed_key(self.team, self.user, label="shared")
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        other_user = self._create_user("other@test.com")
        other_user.join(organization=other_org, level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(other_user)
        response = self.client.post(
            f"/api/projects/{other_team.id}/project_secret_api_keys",
            {"label": "shared", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cannot_access_other_teams_key(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        other_key, _ = _create_managed_key(other_team, self.user)

        for url in [
            f"/api/projects/{self.team.id}/project_secret_api_keys/{other_key.id}/",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            response = self.client.delete(url)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# 2. Scope validation on create
# ===========================================================================


class TestProjectSecretAPIKeyScopeValidation(_AdminBase):
    @parameterized.expand(
        [
            (["feature_flag:read"], True),
            (["feature_flag:write"], False),
            (["query:read"], False),
            (["insight:read"], False),
            (["feature_flag:read", "query:read"], False),
            (["*"], False),
            (["invalid"], False),
            (["feature_flag:invalid"], False),
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
        else:
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_without_scopes_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys/",
            {"label": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_empty_label_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys/",
            {"label": "", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ===========================================================================
# 3. Org-level permissions for management viewset
# ===========================================================================


class TestProjectSecretAPIKeyOrgPermissions(APIBaseTest):
    def test_member_cannot_create(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "nope", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_update(self):
        key, _ = _create_managed_key(self.team, self.user)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "nope"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_delete(self):
        key, _ = _create_managed_key(self.team, self.user)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_list(self):
        _create_managed_key(self.team, self.user)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

    def test_member_can_retrieve(self):
        key, _ = _create_managed_key(self.team, self.user)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            (OrganizationMembership.Level.ADMIN,),
            (OrganizationMembership.Level.OWNER,),
        ]
    )
    def test_admin_and_owner_can_create(self, level):
        self.organization_membership.level = level
        self.organization_membership.save()
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": f"key-{level}", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ===========================================================================
# 4. Authentication layer
# ===========================================================================


class TestProjectSecretAPIKeyAuthentication(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key, self.key_value = _create_managed_key(self.team, self.user)
        _create_feature_flag(self.team)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # --- happy paths ---

    def test_managed_key_authenticates_on_local_evaluation(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("flags", response.json())

    def test_managed_key_authenticates_on_remote_config(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="remote-cfg",
            name="Remote Config",
            filters={
                "groups": [{"rollout_percentage": 100}],
                "payloads": {"true": {"setting": "value"}},
            },
            is_remote_configuration=True,
            active=True,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/remote_config",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- legacy team token backward compat ---

    def test_legacy_team_secret_api_token_works(self):
        legacy_token = generate_random_token_secret()
        self.team.secret_api_token = legacy_token
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(legacy_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_legacy_team_secret_api_token_backup_works(self):
        backup_token = generate_random_token_secret()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token
        self.team.save()

        from posthog.models.team import set_team_in_cache

        set_team_in_cache(backup_token, self.team)

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(backup_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- invalid tokens ---

    def test_invalid_phs_token_returns_401(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer("phs_definitelyinvalidtoken12345678"),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deleted_key_returns_401(self):
        self.key.delete()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- prefix handoff: PersonalAPIKeyAuthentication skips phs_ tokens ---

    def test_personal_api_key_auth_skips_phs_prefix(self):
        from django.test import RequestFactory

        from posthog.auth import PersonalAPIKeyAuthentication as PAK

        factory = RequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {self.key_value}")

        pak = PAK()
        result = pak.find_key_with_source(request)
        # PersonalAPIKeyAuthentication should return None for phs_ tokens
        self.assertIsNone(result)

    # --- header whitespace handling ---

    def test_header_with_trailing_whitespace_still_works(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}  ",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ===========================================================================
# 5. Endpoint access control — phs_ key on restricted endpoints
# ===========================================================================


class TestProjectSecretAPIKeyEndpointRestrictions(APIBaseTest):
    """Project secret API keys should ONLY work on endpoints that explicitly
    include ProjectSecretAPIKeyAuthentication in their authentication_classes."""

    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key, self.key_value = _create_managed_key(self.team, self.user)
        _create_feature_flag(self.team)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # --- feature_flags viewset endpoints WITHOUT ProjectSecretAPIKeyAuthentication ---

    def test_cannot_list_feature_flags(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_create_feature_flag(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "new-flag", "name": "New Flag"},
            format="json",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_retrieve_feature_flag(self):
        flag = FeatureFlag.objects.filter(team=self.team).first()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # --- entirely different viewsets ---

    @parameterized.expand(
        [
            ("insights",),
            ("dashboards",),
            ("actions",),
            ("cohorts",),
        ]
    )
    def test_cannot_access_other_viewset(self, viewset_path):
        response = self.client.get(
            f"/api/projects/{self.team.id}/{viewset_path}/",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # --- management viewset itself cannot be accessed with phs_ key ---

    def test_cannot_list_project_secret_keys(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_create_project_secret_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "nope", "scopes": ["feature_flag:read"]},
            format="json",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cannot_delete_project_secret_key(self):
        response = self.client.delete(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{self.key.id}/",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


# ===========================================================================
# 6. Scope enforcement (ProjectSecretAPIKeyPermission)
# ===========================================================================


class TestProjectSecretAPIKeyScopeEnforcement(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        _create_feature_flag(self.team)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_correct_scope_allows_access(self):
        _, key_value = _create_managed_key(self.team, self.user, scopes=["feature_flag:read"])
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_no_required_scopes_on_endpoint_denies_access(self):
        """Permission class returns False when the endpoint has no required_scopes."""
        key = MagicMock()
        key.scopes = ["feature_flag:read"]
        key.team_id = self.team.id

        mock_request = MagicMock()
        mock_request.successful_authenticator = MagicMock(spec=ProjectSecretAPIKeyAuthentication)
        mock_request.user = MagicMock(spec=ProjectSecretAPIKeyUser)
        mock_request.user.project_secret_api_key = key
        mock_request.method = "GET"

        mock_view = MagicMock()
        mock_view.team_id = self.team.id
        mock_view.required_scopes = None
        mock_view.action = "list"
        # No required_scopes → _get_required_scopes returns None
        del mock_view.required_scopes

        permission = ProjectSecretAPIKeyPermission()
        # Patch _get_required_scopes to return None
        with patch.object(permission, "_get_required_scopes", return_value=None):
            self.assertFalse(permission.has_permission(mock_request, mock_view))

    def test_legacy_team_token_bypasses_scope_check(self):
        legacy_token = generate_random_token_secret()
        self.team.secret_api_token = legacy_token
        self.team.save()

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(legacy_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ===========================================================================
# 7. Team isolation
# ===========================================================================


class TestProjectSecretAPIKeyTeamIsolation(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key, self.key_value = _create_managed_key(self.team, self.user)
        _create_feature_flag(self.team)

        self.other_org = Organization.objects.create(name="Other")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other")
        _create_feature_flag(self.other_team, key="other-flag")

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_cross_team_local_evaluation_denied(self):
        response = self.client.get(
            f"/api/projects/{self.other_team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cross_team_remote_config_denied(self):
        flag = FeatureFlag.objects.create(
            team=self.other_team,
            key="remote-other",
            name="RC",
            filters={
                "groups": [{"rollout_percentage": 100}],
                "payloads": {"true": "val"},
            },
            is_remote_configuration=True,
            active=True,
        )
        response = self.client.get(
            f"/api/projects/{self.other_team.id}/feature_flags/{flag.id}/remote_config",
            **self._bearer(self.key_value),
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_permission_has_object_permission_team_match(self):
        permission = ProjectSecretAPIKeyPermission()

        mock_request = MagicMock()
        mock_request.successful_authenticator = MagicMock(spec=ProjectSecretAPIKeyAuthentication)
        mock_request.user = ProjectSecretAPIKeyUser(self.team, self.key)

        obj = MagicMock()
        obj.team_id = self.team.id
        obj.team = None  # force team_id path
        self.assertTrue(permission.has_object_permission(mock_request, MagicMock(), obj))

    def test_permission_has_object_permission_team_mismatch(self):
        permission = ProjectSecretAPIKeyPermission()

        mock_request = MagicMock()
        mock_request.successful_authenticator = MagicMock(spec=ProjectSecretAPIKeyAuthentication)
        mock_request.user = ProjectSecretAPIKeyUser(self.team, self.key)

        obj = MagicMock()
        obj.team = self.other_team
        self.assertFalse(permission.has_object_permission(mock_request, MagicMock(), obj))

    def test_permission_cross_team_raises_not_found(self):
        mock_request = MagicMock()
        mock_request.successful_authenticator = MagicMock(spec=ProjectSecretAPIKeyAuthentication)
        mock_request.user = MagicMock(spec=ProjectSecretAPIKeyUser)
        mock_request.user.project_secret_api_key = self.key
        mock_request.method = "GET"

        mock_view = MagicMock()
        mock_view.team_id = self.other_team.id

        permission = ProjectSecretAPIKeyPermission()
        with self.assertRaises(NotFound):
            permission.has_permission(mock_request, mock_view)


# ===========================================================================
# 8. ProjectSecretAPIKeyUser
# ===========================================================================


class TestProjectSecretAPIKeyUser(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.key, _ = _create_managed_key(self.team, self.user)

    def test_is_authenticated(self):
        user = ProjectSecretAPIKeyUser(self.team, self.key)
        self.assertTrue(user.is_authenticated)

    def test_has_perm_returns_false(self):
        user = ProjectSecretAPIKeyUser(self.team, self.key)
        self.assertFalse(user.has_perm("any_perm"))

    def test_pk_and_id_are_negative_one(self):
        user = ProjectSecretAPIKeyUser(self.team, self.key)
        self.assertEqual(user.pk, -1)
        self.assertEqual(user.id, -1)

    def test_distinct_id_managed_key(self):
        user = ProjectSecretAPIKeyUser(self.team, self.key)
        self.assertEqual(user.distinct_id, f"ph_secret_project_key:{self.key.id}")

    def test_distinct_id_legacy_token(self):
        user = ProjectSecretAPIKeyUser(self.team, None)
        self.assertEqual(user.distinct_id, "team_secret_api_token")

    def test_str(self):
        user = ProjectSecretAPIKeyUser(self.team, self.key)
        self.assertIn(str(self.team.id), str(user))


# ===========================================================================
# 9. last_used_at tracking
# ===========================================================================


class TestProjectSecretAPIKeyLastUsedAt(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key, self.key_value = _create_managed_key(self.team, self.user)
        _create_feature_flag(self.team)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_first_use_sets_last_used_at(self):
        self.assertIsNone(self.key.last_used_at)
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)

    def test_second_use_within_hour_does_not_update(self):
        now = timezone.now()
        ProjectSecretAPIKey.objects.filter(pk=self.key.pk).update(last_used_at=now)
        self.key.refresh_from_db()

        self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.key.refresh_from_db()
        # Should still be the same value (within a second tolerance)
        self.assertAlmostEqual(self.key.last_used_at.timestamp(), now.timestamp(), delta=2)

    def test_use_after_one_hour_updates(self):
        old_time = timezone.now() - timedelta(hours=2)
        ProjectSecretAPIKey.objects.filter(pk=self.key.pk).update(last_used_at=old_time)
        self.key.refresh_from_db()

        self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(self.key_value),
        )
        self.key.refresh_from_db()
        self.assertGreater(self.key.last_used_at, old_time + timedelta(hours=1))

    def test_last_used_at_update_skips_cache_invalidation(self):
        with patch("posthog.models.project_secret_api_key.invalidate_project_secret_api_key_cache") as mock_invalidate:
            self.key.last_used_at = timezone.now()
            self.key.save(update_fields=["last_used_at"])
            mock_invalidate.assert_not_called()

    def test_scopes_update_triggers_cache_invalidation(self):
        with patch("posthog.models.project_secret_api_key.invalidate_project_secret_api_key_cache") as mock_invalidate:
            self.key.scopes = ["feature_flag:read"]
            self.key.save(update_fields=["scopes"])
            mock_invalidate.assert_called_once()


# ===========================================================================
# 10. Full lifecycle integration tests
# ===========================================================================


class TestProjectSecretAPIKeyLifecycle(APIBaseTest):
    """End-to-end: create key via API → use it → roll → use new → delete → old fails."""

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        _create_feature_flag(self.team)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_roll_invalidates_old_key(self):
        # Create via API
        create_resp = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "lifecycle", "scopes": ["feature_flag:read"]},
        )
        key_id = create_resp.json()["id"]
        old_value = create_resp.json()["value"]

        # Old value works
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(old_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Roll the key
        self.client.force_login(self.user)
        roll_resp = self.client.post(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}/roll")
        new_value = roll_resp.json()["value"]

        # Old value no longer works
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(old_value),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # New value works
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(new_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_invalidates_key(self):
        create_resp = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "to-delete", "scopes": ["feature_flag:read"]},
        )
        key_id = create_resp.json()["id"]
        key_value = create_resp.json()["value"]

        # Works before delete
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Delete
        self.client.force_login(self.user)
        self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key_id}/")

        # No longer works
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/local_evaluation",
            **self._bearer(key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ===========================================================================
# 11. Activity logging
# ===========================================================================


class TestProjectSecretAPIKeyActivityLogging(_AdminBase):
    def test_create_logs_activity(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "Activity Test", "scopes": ["feature_flag:read"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        key_id = response.json()["id"]
        activity = ActivityLog.objects.filter(
            scope="ProjectSecretAPIKey", activity="created", item_id=str(key_id)
        ).first()
        assert activity is not None
        self.assertEqual(activity.team_id, self.team.id)

    def test_update_logs_activity(self):
        key, _ = _create_managed_key(self.team, self.user, label="Initial")
        self.client.put(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}",
            {"label": "Updated"},
        )
        activity = (
            ActivityLog.objects.filter(scope="ProjectSecretAPIKey", activity="updated", item_id=str(key.id))
            .order_by("-created_at")
            .first()
        )
        assert activity is not None
        assert activity.detail is not None
        changes = activity.detail.get("changes", [])
        self.assertTrue(any(c["field"] == "label" for c in changes))

    def test_delete_logs_activity(self):
        key, _ = _create_managed_key(self.team, self.user)
        self.client.delete(f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/")
        activity = ActivityLog.objects.filter(
            scope="ProjectSecretAPIKey", activity="deleted", item_id=str(key.id)
        ).first()
        assert activity is not None


# ===========================================================================
# 12. Personal API key managing project secret keys
# ===========================================================================


class TestProjectSecretAPIKeyViaPersonalAPIKey(_AdminBase):
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

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.personal_key_value}"}

    def test_can_create_with_personal_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "via personal", "scopes": ["feature_flag:read"]},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_can_list_with_personal_key(self):
        _create_managed_key(self.team, self.user)
        response = self.client.get(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            **self._auth(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

    def test_can_delete_with_personal_key(self):
        key, _ = _create_managed_key(self.team, self.user)
        response = self.client.delete(
            f"/api/projects/{self.team.id}/project_secret_api_keys/{key.id}/",
            **self._auth(),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_personal_key_without_project_write_scope_fails(self):
        self.personal_key.scopes = ["project:read"]
        self.personal_key.save()
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "nope", "scopes": ["feature_flag:read"]},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# 13. phs_ token pass-through in auth chain
# ===========================================================================


class TestPHSTokenPassThroughInAuthChain(APIBaseTest):
    """When a phs_ token hits an endpoint whose auth chain does NOT include
    ProjectSecretAPIKeyAuthentication, the PersonalAPIKeyAuthentication must
    skip it (return None) so it falls through the entire chain and results
    in 401 — NOT a personal-key-not-found error or accidental auth."""

    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.key, self.key_value = _create_managed_key(self.team, self.user)

    def _bearer(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_phs_token_on_personal_key_only_endpoint_returns_401(self):
        """The project_secret_api_keys management endpoint only accepts
        PersonalAPIKeyAuthentication + SessionAuthentication. A phs_ token
        should be skipped by PersonalAPIKeyAuthentication and result in 401."""
        response = self.client.get(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_phs_token_on_default_auth_viewset_returns_403(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/",
            **self._bearer(self.key_value),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_phs_token_not_confused_with_personal_key(self):
        """Directly verify that PersonalAPIKeyAuthentication.authenticate()
        returns None (not an error) for a phs_ token, allowing the chain
        to continue."""
        from django.test import RequestFactory

        from posthog.auth import PersonalAPIKeyAuthentication

        factory = RequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {self.key_value}")

        pak = PersonalAPIKeyAuthentication()
        result = pak.authenticate(request)
        self.assertIsNone(result)
