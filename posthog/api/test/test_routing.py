from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone

from rest_framework import viewsets

from posthog.api.annotation import AnnotationSerializer
from posthog.api.routing import DefaultRouterPlusPlus, TeamAndOrgViewSetMixin
from posthog.api.test.test_oauth import generate_rsa_key
from posthog.models.annotation import Annotation
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team.team import Team


class FooViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer


class ScopedFooViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "annotation"
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer


test_router = DefaultRouterPlusPlus()

test_environments_router = test_router.register(r"environments", FooViewSet, "environments")
test_environments_router.register(r"foos", FooViewSet, "environment_foos", ["team_id"])

test_projects_router = test_router.register(r"projects", FooViewSet, "projects")
test_projects_router.register(r"foos", FooViewSet, "project_foos", ["project_id"])

test_organizations_router = test_router.register(r"organizations", FooViewSet, "organizations")
test_organizations_router.register(r"foos", FooViewSet, "organization_foos", ["organization_id"])

scoped_test_environments_router = test_router.register(r"scoped_environments", ScopedFooViewSet, "scoped_environments")
scoped_test_environments_router.register(r"scoped_foos", ScopedFooViewSet, "scoped_environment_foos", ["team_id"])

scoped_test_projects_router = test_router.register(r"scoped_projects", ScopedFooViewSet, "scoped_projects")
scoped_test_projects_router.register(r"scoped_foos", ScopedFooViewSet, "scoped_project_foos", ["project_id"])

scoped_test_organizations_router = test_router.register(
    r"scoped_organizations", ScopedFooViewSet, "scoped_organizations"
)
scoped_test_organizations_router.register(
    r"scoped_foos", ScopedFooViewSet, "scoped_organization_foos", ["organization_id"]
)


urlpatterns = [
    path("api/", include(test_router.urls)),
]


@override_settings(ROOT_URLCONF=__name__)  # Use `urlpatterns` from this file and not from `posthog.urls`
class TestTeamAndOrgViewSetMixin(APIBaseTest):
    test_annotation: Annotation

    def setUp(self):
        super().setUp()
        other_org, _, other_org_team = Organization.objects.bootstrap(user=self.user)
        self.other_org_annotation = Annotation.objects.create(team=other_org_team, organization=other_org)
        _, other_project_team = Project.objects.create_with_team(
            initiating_user=self.user, organization=self.organization
        )
        self.other_project_annotation = Annotation.objects.create(
            team=other_project_team, organization=self.organization
        )
        other_team = Team.objects.create(organization=self.organization, project=self.project)
        self.other_team_annotation = Annotation.objects.create(team=other_team, organization=self.organization)
        self.current_team_annotation = Annotation.objects.create(team=self.team, organization=self.organization)

    def test_environment_nested_filtering(self):
        response = self.client.get(f"/api/environments/{self.team.id}/foos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)  # Just current_team_annotation

    def test_project_nested_filtering(self):
        response = self.client.get(f"/api/projects/{self.team.id}/foos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)  # Both current_team_annotation and other_team_annotation

    def test_organization_nested_filtering(self):
        response = self.client.get(f"/api/organizations/{self.organization.id}/foos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 3)  # All except other_org_annotation

    def test_cannot_override_special_methods(self):
        with pytest.raises(Exception) as e:

            class _TestViewSet1(TeamAndOrgViewSetMixin):
                def get_permissions(self):
                    pass

        assert (
            str(e.value)
            == "Method get_permissions is protected and should not be overridden. Add additional 'permission_classes' via the class attribute instead. Or in exceptional use cases use dangerously_get_permissions instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet2(TeamAndOrgViewSetMixin):
                def get_authenticators(self):
                    pass

        assert (
            str(e.value)
            == "Method get_authenticators is protected and should not be overridden. Add additional 'authentication_classes' via the class attribute instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet3(TeamAndOrgViewSetMixin):
                def get_queryset(self):
                    pass

        assert (
            str(e.value)
            == "Method get_queryset is protected and should not be overridden. Use safely_get_queryset instead"
        )

        with pytest.raises(Exception) as e:

            class _TestViewSet4(TeamAndOrgViewSetMixin):
                def get_object(self):
                    pass

        assert (
            str(e.value) == "Method get_object is protected and should not be overridden. Use safely_get_object instead"
        )


@override_settings(
    ROOT_URLCONF=__name__,
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    },
)
class TestOAuthAccessTokenAuthentication(APIBaseTest):
    """Test that OAuth access tokens work through the routing layer with proper permissions"""

    def setUp(self):
        super().setUp()

        self.oauth_app = OAuthApplication.objects.create(
            name="Test App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

        self.access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="pha_test_oauth_access_token_123",
            expires=timezone.now() + timedelta(hours=1),
            scope="annotation:read",
        )

    def test_oauth_token_can_access_team_resources(self):
        annotation = Annotation.objects.create(team=self.team, organization=self.organization, content="Test note")

        response = self.client.get(
            f"/api/scoped_environments/{self.team.id}/scoped_foos/",
            HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], annotation.id)

    def test_oauth_token_cannot_access_other_team_resources(self):
        """Test that OAuth tokens respect team boundaries"""
        # Create a different user and their organization (user is NOT a member of this org)
        from posthog.models import User

        other_user = User.objects.create(email="other@example.com")
        other_org, _, other_team = Organization.objects.bootstrap(user=other_user)
        Annotation.objects.create(team=other_team, organization=other_org)

        response = self.client.get(
            f"/api/scoped_environments/{other_team.id}/scoped_foos/",
            HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}",
        )

        # Should not have access to other org's team (self.user is not a member of other_org)
        self.assertEqual(response.status_code, 403)

    def test_oauth_token_can_access_organization_resources(self):
        """Test that OAuth tokens can access organization-scoped resources"""
        Annotation.objects.create(team=self.team, organization=self.organization)

        response = self.client.get(
            f"/api/scoped_organizations/{self.organization.id}/scoped_foos/",
            HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_oauth_token_fails_with_expired_token(self):
        """Test that expired OAuth tokens are rejected"""
        expired_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token="pha_expired_oauth_token_123",
            expires=timezone.now() - timedelta(hours=1),
            scope="annotation:read",
        )

        response = self.client.get(
            f"/api/scoped_environments/{self.team.id}/scoped_foos/",
            HTTP_AUTHORIZATION=f"Bearer {expired_token.token}",
        )

        self.assertEqual(response.status_code, 401)

    def test_oauth_token_works_alongside_session_auth(self):
        """Test that OAuth authentication is part of the authentication chain"""
        # First, verify session auth works
        Annotation.objects.create(team=self.team, organization=self.organization)
        response = self.client.get(f"/api/scoped_environments/{self.team.id}/scoped_foos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

        # Logout and verify OAuth token works
        self.client.logout()
        response = self.client.get(f"/api/scoped_environments/{self.team.id}/scoped_foos/")
        self.assertEqual(response.status_code, 401)

        # Now use OAuth token
        response = self.client.get(
            f"/api/scoped_environments/{self.team.id}/scoped_foos/",
            HTTP_AUTHORIZATION=f"Bearer {self.access_token.token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
