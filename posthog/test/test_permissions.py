from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import Mock

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIRequestFactory

from posthog.api.test.test_oauth import generate_rsa_key
from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.permissions import AccessControlPermission
from posthog.rbac.user_access_control import UserAccessControl

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


class TestAccessControlPermission(BaseTest):
    """
    Test the AccessControlPermission class to ensure it properly handles
    specific object access when users have "none" resource access.
    """

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        self.role = Role.objects.create(name="Test Role", organization=self.organization)
        RoleMembership.objects.create(user=self.user, role=self.role)

        self.factory = APIRequestFactory()
        self.permission = AccessControlPermission()

        self.other_user = self._create_user("other_user")

        # Create test notebooks
        from products.notebooks.backend.models import Notebook

        self.notebook_1 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 1")
        self.notebook_2 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 2")

    def _create_access_control(
        self, resource="notebook", resource_id=None, access_level="editor", organization_member=None, role=None
    ):
        """Helper to create access control entries"""
        ac, _ = AccessControl.objects.get_or_create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=organization_member,
            role=role,
        )
        ac.access_level = access_level
        ac.save()
        return ac

    def _create_real_view(self, action="list", pk=None):
        """Helper to create a real NotebookViewSet instance"""
        from products.notebooks.backend.api.notebook import NotebookViewSet

        view = NotebookViewSet()
        view.action = action
        view.kwargs = {"pk": pk} if pk else {}
        view.team = self.team
        view.user_access_control = UserAccessControl(self.user, self.team)
        view.request = Mock()
        view.request.user = self.user
        return view

    def _create_mock_request(self, method="GET", user=None):
        """Helper to create a mock request"""
        if user is None:
            user = self.user

        request = self.factory.get("/") if method == "GET" else self.factory.post("/")
        request.user = user
        request.successful_authenticator = Mock()  # type: ignore
        request.successful_authenticator.__class__.__name__ = "SessionAuthentication"
        return request

    def test_has_permission_with_resource_access(self):
        """Test API permission when user has resource-level access"""
        # Give user resource-level access to notebooks
        self._create_access_control(
            resource="notebook",
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should have permission
        assert self.permission.has_permission(request, view) is True

    def test_has_permission_with_none_resource_but_specific_access(self):
        """Test API permission when user has 'none' resource access but specific object access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should have permission due to specific access fallback
        assert self.permission.has_permission(request, view) is True

    def test_has_permission_with_none_resource_and_no_specific_access(self):
        """Test API permission when user has 'none' resource access and no specific access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should NOT have permission
        assert self.permission.has_permission(request, view) is False

    def test_has_object_permission_with_specific_access(self):
        """Test object-level permission when user has specific access to the object"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="retrieve", pk=str(self.notebook_1.id))

        # Should have object permission for notebook_1
        assert self.permission.has_object_permission(request, view, self.notebook_1) is True

    def test_has_object_permission_without_specific_access(self):
        """Test object-level permission when user lacks specific access to the object"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        request = self._create_mock_request()
        view = self._create_real_view(action="retrieve", pk=str(self.notebook_2.id))

        # Should NOT have object permission for notebook_2
        assert self.permission.has_object_permission(request, view, self.notebook_2) is False

    def test_has_permission_for_create_action_with_none_resource_access(self):
        """Test that create actions are blocked when user has 'none' resource access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1 (shouldn't matter for creation)
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request(method="POST")
        view = self._create_real_view(action="create")

        # Should NOT have permission to create (resource-level check should fail)
        assert self.permission.has_permission(request, view) is False

    def test_has_permission_for_create_action_with_resource_access(self):
        """Test that create actions work when user has resource-level access"""
        # Give user resource-level access to notebooks
        self._create_access_control(
            resource="notebook",
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request(method="POST")
        view = self._create_real_view(action="create")

        # Should have permission to create
        assert self.permission.has_permission(request, view) is True

    def test_has_permission_with_project_secret_api_token_authentication(self):
        """Test that has_permission returns True when authenticated via project secret API token"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        request = self._create_mock_request()
        request.successful_authenticator = ProjectSecretAPIKeyAuthentication()
        view = self._create_real_view(action="list")

        # Should have permission when authenticated via project secret API token
        assert self.permission.has_permission(request, view) is True


class TestProjectSecretAPITokenPermission(BaseTest):
    """Direct unit tests for ProjectSecretAPITokenPermission.has_permission method"""

    def setUp(self):
        super().setUp()
        from posthog.permissions import ProjectSecretAPITokenPermission

        self.permission = ProjectSecretAPITokenPermission()

    def _create_mock_request(self, authenticator_class=None, view_name="featureflag-local-evaluation", user=None):
        """Helper to create a mock request with specified authenticator and view name"""
        request = Mock()

        # Mock the authenticator
        mock_authenticator = Mock()
        if authenticator_class:
            mock_authenticator.__class__ = authenticator_class
        request.successful_authenticator = mock_authenticator

        # Mock resolver_match with view_name
        request.resolver_match = Mock()
        request.resolver_match.view_name = view_name

        # Set user if provided
        if user:
            request.user = user

        return request

    def _create_mock_view(self, team=None, raise_exception=None):
        """Helper to create a mock view with specified team or exception"""
        view = Mock()

        if raise_exception:
            # Configure the mock to raise the exception when team is accessed
            view.team = Mock(side_effect=raise_exception)
        else:
            view.team = team

        return view

    def _create_mock_team(self, team_id=1):
        """Helper to create a mock team with specified ID"""
        team = Mock()
        team.id = team_id
        return team

    def _create_mock_user(self, team):
        """Helper to create a mock user with specified team"""
        user = Mock()
        user.team = team
        return user

    def test_has_permission_with_non_project_secret_authenticator(self):
        """Should return True when not using ProjectSecretAPIKeyAuthentication"""
        from posthog.auth import PersonalAPIKeyAuthentication

        request = self._create_mock_request(authenticator_class=PersonalAPIKeyAuthentication)
        view = self._create_mock_view()

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_with_project_secret_authenticator_disallowed_endpoint(self):
        """Should return False for disallowed endpoints"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        request = self._create_mock_request(
            authenticator_class=ProjectSecretAPIKeyAuthentication, view_name="some-other-endpoint"
        )
        view = self._create_mock_view()

        result = self.permission.has_permission(request, view)

        self.assertFalse(result)

    @parameterized.expand(
        [
            ("featureflag-local-evaluation",),
            ("project_feature_flags-remote-config",),
            ("project_feature_flags-local-evaluation",),
        ]
    )
    def test_has_permission_to_secret_api_token_secured_endpoints(self, endpoint_name):
        """Should allow project_feature_flags endpoints with matching teams"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        team = self._create_mock_team(team_id=1)
        user = self._create_mock_user(team)

        request = self._create_mock_request(
            authenticator_class=ProjectSecretAPIKeyAuthentication,
            view_name=endpoint_name,
            user=user,
        )
        view = self._create_mock_view(team=team)

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_unknown_endpoint(self):
        """Should reject unknown endpoints"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        request = self._create_mock_request(
            authenticator_class=ProjectSecretAPIKeyAuthentication, view_name="unknown-endpoint"
        )
        view = self._create_mock_view()

        result = self.permission.has_permission(request, view)

        self.assertFalse(result)

    def test_has_permission_matching_teams(self):
        """Should return True when authenticated team matches resolved team"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        team = self._create_mock_team(team_id=1)
        user = self._create_mock_user(team)

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication, user=user)
        view = self._create_mock_view(team=team)

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_mismatched_teams(self):
        """Should return False when authenticated team doesn't match resolved team"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        team1 = self._create_mock_team(team_id=1)
        team2 = self._create_mock_team(team_id=2)
        user = self._create_mock_user(team1)

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication, user=user)
        view = self._create_mock_view(team=team2)

        result = self.permission.has_permission(request, view)

        self.assertFalse(result)

    def test_has_permission_view_team_resolution_fails_with_team_does_not_exist(self):
        """Should return True when view.team raises Team.DoesNotExist"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        team = self._create_mock_team(team_id=1)
        user = self._create_mock_user(team)

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication, user=user)

        # Create a view class that raises Team.DoesNotExist when team is accessed
        class MockView:
            @property
            def team(self):
                raise Team.DoesNotExist("Team not found")

        view = MockView()
        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_view_missing_team_attribute(self):
        """Should return True when view.team raises AttributeError"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        team = self._create_mock_team(team_id=1)
        user = self._create_mock_user(team)

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication, user=user)

        # Create a view class that raises AttributeError when team is accessed
        class MockView:
            @property
            def team(self):
                raise AttributeError("'view' object has no attribute 'team'")

        view = MockView()
        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_no_view_name(self):
        """Should handle missing view_name gracefully"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication, view_name=None)
        view = self._create_mock_view()

        result = self.permission.has_permission(request, view)

        # None is not in the allowed endpoints tuple, so this should return False
        self.assertFalse(result)


class TestTeamMemberAccessPermission(BaseTest):
    """Direct unit tests for TeamMemberAccessPermission.has_permission method"""

    def setUp(self):
        super().setUp()
        from posthog.permissions import TeamMemberAccessPermission

        self.permission = TeamMemberAccessPermission()

    def _create_mock_request(self, authenticator_class=None, user=None):
        """Helper to create a mock request with specified authenticator"""
        request = Mock()

        # Mock the authenticator
        mock_authenticator = Mock()
        if authenticator_class:
            mock_authenticator.__class__ = authenticator_class
        request.successful_authenticator = mock_authenticator

        # Set user if provided
        if user:
            request.user = user

        return request

    def _create_mock_view(self, team=None, raise_exception=None, user_permissions=None):
        """Helper to create a mock view with specified team or exception"""
        view = Mock()

        if raise_exception:
            # Configure the mock to raise the exception when team is accessed
            view.team = Mock(side_effect=raise_exception)
        else:
            view.team = team

        # Set user_permissions if provided
        if user_permissions:
            view.user_permissions = user_permissions

        return view

    def _create_mock_team(self, team_id=1):
        """Helper to create a mock team with specified ID"""
        team = Mock()
        team.id = team_id
        return team

    def _create_mock_user_permissions(self, effective_membership_level=None):
        """Helper to create a mock user_permissions with specified effective membership level"""
        user_permissions = Mock()
        current_team = Mock()
        current_team.effective_membership_level = effective_membership_level
        user_permissions.current_team = current_team
        return user_permissions

    def test_has_permission_with_project_secret_api_token_authenticator(self):
        """Should return True when using ProjectSecretAPIKeyAuthentication"""
        from posthog.auth import ProjectSecretAPIKeyAuthentication

        request = self._create_mock_request(authenticator_class=ProjectSecretAPIKeyAuthentication)
        view = self._create_mock_view()

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_with_non_project_secret_authenticator_and_valid_membership(self):
        """Should return True when not using project secret auth and user has valid membership"""
        from posthog.auth import PersonalAPIKeyAuthentication
        from posthog.models.organization import OrganizationMembership

        team = self._create_mock_team()
        user_permissions = self._create_mock_user_permissions(
            effective_membership_level=OrganizationMembership.Level.MEMBER
        )

        request = self._create_mock_request(authenticator_class=PersonalAPIKeyAuthentication)
        view = self._create_mock_view(team=team, user_permissions=user_permissions)

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_with_non_project_secret_authenticator_and_no_membership(self):
        """Should return False when not using project secret auth and user has no membership"""
        from posthog.auth import PersonalAPIKeyAuthentication

        team = self._create_mock_team()
        user_permissions = self._create_mock_user_permissions(effective_membership_level=None)

        request = self._create_mock_request(authenticator_class=PersonalAPIKeyAuthentication)
        view = self._create_mock_view(team=team, user_permissions=user_permissions)

        result = self.permission.has_permission(request, view)

        self.assertFalse(result)

    def test_has_permission_with_team_does_not_exist_exception(self):
        """Should return True when view.team raises Team.DoesNotExist"""
        from posthog.auth import PersonalAPIKeyAuthentication

        request = self._create_mock_request(authenticator_class=PersonalAPIKeyAuthentication)
        view = self._create_mock_view(raise_exception=Team.DoesNotExist("Team not found"))

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)

    def test_has_permission_with_admin_membership(self):
        """Should return True when user has admin membership level"""
        from posthog.auth import PersonalAPIKeyAuthentication
        from posthog.models.organization import OrganizationMembership

        team = self._create_mock_team()
        user_permissions = self._create_mock_user_permissions(
            effective_membership_level=OrganizationMembership.Level.ADMIN
        )

        request = self._create_mock_request(authenticator_class=PersonalAPIKeyAuthentication)
        view = self._create_mock_view(team=team, user_permissions=user_permissions)

        result = self.permission.has_permission(request, view)

        self.assertTrue(result)


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenAPIScopePermission(BaseTest):
    """Test that OAuth access tokens properly enforce API scopes via APIScopePermission"""

    def setUp(self):
        super().setUp()

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create access token with limited scopes
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_oauth_scoped_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="feature_flag:read",
        )

    def _do_request(self, url, method="GET", data=None):
        """Helper to make requests with OAuth token"""
        if method == "GET":
            return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}")
        elif method == "POST":
            return self.client.post(
                url, data or {}, format="json", HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}"
            )
        elif method == "PATCH":
            return self.client.patch(
                url, data or {}, format="json", HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}"
            )

    def test_denies_token_with_no_scopes(self):
        """OAuth tokens with empty scopes should not have access"""
        self.access_token.scope = ""
        self.access_token.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "OAuth token has no scopes and cannot access this resource")

    def test_forbids_scoped_access_for_unsupported_endpoint(self):
        """Even * scope isn't allowed for unsupported endpoints"""
        self.access_token.scope = "*"
        self.access_token.save()
        response = self._do_request(f"/api/projects/{self.team.id}/search")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "This action does not support Personal API Key access")

    def test_allows_derived_scope_for_read(self):
        """OAuth token with feature_flag:read can read feature flags"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)

    def test_denies_derived_scope_for_write(self):
        """OAuth token with feature_flag:read cannot write feature flags"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/", method="POST")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "API key missing required scope 'feature_flag:write'")

    def test_allows_action_with_required_scopes(self):
        """OAuth token can access endpoints that match its scopes"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, 200)

    def test_forbids_action_with_other_scope(self):
        """OAuth token cannot access endpoints requiring different scopes"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/activity")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "API key missing required scope 'activity_log:read'")

    def test_allows_action_with_multiple_scopes(self):
        """OAuth token with multiple scopes can access all matching endpoints"""
        self.access_token.scope = "feature_flag:write activity_log:read"
        self.access_token.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/activity")
        self.assertEqual(response.status_code, 200)

    def test_write_scope_allows_read_operations(self):
        """OAuth token with write scope should also allow read operations"""
        self.access_token.scope = "feature_flag:write"
        self.access_token.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)

    def test_wildcard_scope_allows_all_supported_endpoints(self):
        """OAuth token with * scope can access all supported endpoints"""
        self.access_token.scope = "*"
        self.access_token.save()
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenWithOrganizationScoping(BaseTest):
    """Test that OAuth access tokens properly enforce organization scoping"""

    def setUp(self):
        super().setUp()

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create org-scoped access token
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_org_scoped_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="*",
            scoped_organizations=[str(self.organization.id)],
            scoped_teams=[],
        )

    def _do_request(self, url):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}")

    def test_allows_access_to_scoped_org(self):
        """OAuth token scoped to an org can access that org"""
        response = self._do_request(f"/api/organizations/{self.organization.id}/")
        self.assertEqual(response.status_code, 200)

    def test_allows_access_to_scoped_org_teams(self):
        """OAuth token scoped to an org can access teams in that org"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)

    def test_denies_access_to_non_scoped_org_and_team(self):
        """OAuth token scoped to one org cannot access other orgs"""

        other_user = User.objects.create(email="other@example.com")
        other_org, _, _ = Organization.objects.bootstrap(user=other_user)

        response = self._do_request(f"/api/organizations/{other_org.id}/")

        self.assertEqual(response.status_code, 404)


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenWithTeamScoping(BaseTest):
    """Test that OAuth access tokens properly enforce team scoping"""

    def setUp(self):
        super().setUp()

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create team-scoped access token
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_team_scoped_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="*",
            scoped_organizations=[],
            scoped_teams=[self.team.id],
        )

    def _do_request(self, url):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}")

    def test_allows_access_to_scoped_team(self):
        """OAuth token scoped to a team can access that team"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)

    def test_denies_access_to_non_scoped_team(self):
        """OAuth token scoped to one team cannot access other teams"""

        other_user = User.objects.create(email="other@example.com")
        _, _, other_team = Organization.objects.bootstrap(user=other_user)

        response = self._do_request(f"/api/projects/{other_team.id}/feature_flags/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("does not have access to the requested project", response.json()["detail"])


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenWithBothTeamAndOrgScoping(BaseTest):
    """Test that OAuth access tokens properly enforce scoping when both teams and orgs are defined"""

    def setUp(self):
        super().setUp()

        # Create a second team in the same org
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2", project=self.project)

        # Create a second org with a team
        _, self.project2, self.other_org_team = Organization.objects.bootstrap(
            user=self.user, name="Other Organization"
        )

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create access token scoped to specific org and specific team within that org
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_mixed_scoped_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="*",
            scoped_organizations=[str(self.organization.id)],
            scoped_teams=[self.team.id],
        )

    def _do_request(self, url):
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}")

    def test_allows_access_to_scoped_team(self):
        """OAuth token with both org and team scopes allows access to the scoped team"""
        response = self._do_request(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(response.status_code, 200)

    def test_denies_access_to_other_team_in_scoped_org(self):
        """OAuth token with both org and team scopes denies access to other teams in the same org"""
        response = self._do_request(f"/api/projects/{self.team2.id}/feature_flags/")
        # Returns 404 because the user is a member of the org but the token is scoped to a different team
        self.assertEqual(response.status_code, 404)

    def test_denies_access_to_team_in_non_scoped_org(self):
        """OAuth token with both org and team scopes denies access to teams in other orgs"""
        response = self._do_request(f"/api/projects/{self.other_org_team.id}/feature_flags/")
        self.assertEqual(response.status_code, 403)

    def test_denies_access_to_org_endpoint_when_teams_scoped(self):
        """OAuth token with scoped_teams cannot access org endpoints (current limitation)"""
        response = self._do_request(f"/api/organizations/{self.organization.id}/")
        # When scoped_teams is set, org endpoints are denied because the logic requires team-based endpoints
        self.assertEqual(response.status_code, 403)
        self.assertIn("only supported on project-based endpoints", response.json()["detail"])


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenExpiration(BaseTest):
    """Test that expired OAuth access tokens are properly rejected"""

    def setUp(self):
        super().setUp()

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create a valid access token
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_expiring_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="feature_flag:read",
        )

    def _do_request(self, token=None):
        token = token or self.access_token.token
        return self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_valid_token_allows_access(self):
        """A valid non-expired OAuth token allows access"""
        response = self._do_request()
        self.assertEqual(response.status_code, 200)

    def test_expired_token_denies_access(self):
        """An expired OAuth token denies access"""
        # Expire the token
        self.access_token.expires = timezone.now() - timedelta(hours=1)
        self.access_token.save()

        response = self._do_request()
        self.assertEqual(response.status_code, 401)

    def test_token_works_then_expires_then_fails(self):
        """OAuth token works when valid, then fails after expiration"""
        # First verify it works
        response = self._do_request()
        self.assertEqual(response.status_code, 200)

        # Expire the token
        self.access_token.expires = timezone.now() - timedelta(hours=1)
        self.access_token.save()

        # Verify it no longer works
        response = self._do_request()
        self.assertEqual(response.status_code, 401)


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenUserMembership(BaseTest):
    """Test that OAuth tokens respect current user membership (not historical)"""

    def setUp(self):
        super().setUp()

        # Create OAuth application
        self.oauth_application = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        # Create a valid access token
        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_membership_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="feature_flag:read",
        )

    def _do_request(self, token=None):
        token = token or self.access_token.token
        return self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_token_works_with_membership(self):
        """OAuth token works when user has org membership"""
        response = self._do_request()
        self.assertEqual(response.status_code, 200)

    def test_token_fails_after_user_leaves_organization(self):
        """OAuth token stops working when user leaves the organization"""
        from posthog.models import OrganizationMembership

        # First verify token works
        response = self._do_request()
        self.assertEqual(response.status_code, 200)

        # Remove user from organization
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        # Verify token no longer works (membership check fails)
        response = self._do_request()
        self.assertEqual(response.status_code, 403)  # Forbidden - user no longer has org membership

    def test_team_scoped_token_fails_when_user_not_in_team_org(self):
        """OAuth token scoped to a team requires user to be in that team's organization"""
        from posthog.models import Organization, User

        # Create a different organization with a team (self.user is NOT a member)
        other_user = User.objects.create(email="other@example.com")
        other_org, _, other_team = Organization.objects.bootstrap(user=other_user)

        # Create a token scoped to the other team
        other_team_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="pha_test_other_team_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="feature_flag:read",
            scoped_teams=[other_team.id],
        )

        # Verify token does NOT work because user is not in that org
        response = self.client.get(
            f"/api/projects/{other_team.id}/feature_flags/",
            HTTP_AUTHORIZATION=f"Bearer {other_team_token.token}",
        )
        self.assertEqual(response.status_code, 403)  # Forbidden - user not in org
