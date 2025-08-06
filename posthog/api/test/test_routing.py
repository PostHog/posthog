import pytest
from unittest.mock import Mock, patch

from posthog.api.routing import TeamAndOrgViewSetMixin
from django.test import override_settings
from django.urls import include, path
from rest_framework import viewsets
from rest_framework.test import APIRequestFactory
from posthog.api.annotation import AnnotationSerializer
from posthog.api.routing import DefaultRouterPlusPlus
from posthog.models.annotation import Annotation
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


class FooViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer


test_router = DefaultRouterPlusPlus()

test_environments_router = test_router.register(r"environments", FooViewSet, "environments")
test_environments_router.register(r"foos", FooViewSet, "environment_foos", ["team_id"])

test_projects_router = test_router.register(r"projects", FooViewSet, "projects")
test_projects_router.register(r"foos", FooViewSet, "project_foos", ["project_id"])

test_organizations_router = test_router.register(r"organizations", FooViewSet, "organizations")
test_organizations_router.register(r"foos", FooViewSet, "organization_foos", ["organization_id"])


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


class TestTeamAndOrgViewSetMixinProjectApiToken(APIBaseTest):
    """Test the _get_explicit_project_api_key and _get_team_from_request methods."""

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.viewset = FooViewSet()

    @patch("posthog.api.test.test_routing.FooViewSet.request", create=True)
    def test_get_explicit_project_api_key_with_dict_data(self, mock_request):
        """Test _get_explicit_project_api_key returns token when request.data is a dict with project_api_key."""
        mock_request.method = "POST"
        mock_request.data = {"project_api_key": "test_token", "other_data": "value"}
        self.viewset.request = mock_request

        result = self.viewset._get_explicit_project_api_key()
        self.assertEqual(result, "test_token")

    @patch("posthog.api.test.test_routing.FooViewSet.request", create=True)
    def test_get_explicit_project_api_key_with_dict_data_no_token(self, mock_request):
        """Test _get_explicit_project_api_key returns None when request.data is a dict without project_api_key."""
        mock_request.method = "POST"
        mock_request.data = {"other_data": "value"}
        self.viewset.request = mock_request

        result = self.viewset._get_explicit_project_api_key()
        self.assertIsNone(result)

    @patch("posthog.api.test.test_routing.FooViewSet.request", create=True)
    def test_get_explicit_project_api_key_with_list_data(self, mock_request):
        """Test _get_explicit_project_api_key returns None when request.data is a list (bulk operations)."""
        mock_request.method = "POST"
        mock_request.data = [{"project_api_key": "test_token"}]
        self.viewset.request = mock_request

        result = self.viewset._get_explicit_project_api_key()
        self.assertIsNone(result)

    @patch("posthog.api.test.test_routing.FooViewSet.request", create=True)
    def test_get_explicit_project_api_key_with_get_request(self, mock_request):
        """Test _get_explicit_project_api_key returns None for GET requests."""
        mock_request.method = "GET"
        mock_request.data = {"project_api_key": "test_token"}
        self.viewset.request = mock_request

        result = self.viewset._get_explicit_project_api_key()
        self.assertIsNone(result)

    @patch("posthog.api.test.test_routing.FooViewSet.request", create=True)
    def test_get_explicit_project_api_key_no_data_attribute(self, mock_request):
        """Test _get_explicit_project_api_key returns None when request has no data attribute."""
        mock_request.method = "POST"
        # Don't set data attribute to simulate missing data attribute
        delattr(mock_request, "data")
        self.viewset.request = mock_request

        result = self.viewset._get_explicit_project_api_key()
        self.assertIsNone(result)

    @patch("posthog.api.routing.get_token")
    @patch("posthog.models.team.team.Team.objects.get_team_from_token")
    def test_get_team_from_request_with_explicit_token(self, mock_get_team_from_token, mock_get_token):
        """Test _get_team_from_request uses explicit project_api_key from request body when available."""
        # Setup mocks
        mock_team = Mock()
        mock_get_team_from_token.return_value = mock_team
        mock_get_token.return_value = None  # Shouldn't be called when explicit token exists

        # Create request with explicit project_api_key
        request = self.factory.post("/test/", {"project_api_key": "explicit_token"})
        self.viewset.request = request

        # Mock _get_explicit_project_api_key to return the token
        with patch.object(self.viewset, "_get_explicit_project_api_key", return_value="explicit_token"):
            result = self.viewset._get_team_from_request()

        # Verify result and calls
        self.assertEqual(result, mock_team)
        mock_get_team_from_token.assert_called_once_with("explicit_token")
        mock_get_token.assert_not_called()

    @patch("posthog.api.routing.get_token")
    @patch("posthog.models.team.team.Team.objects.get_team_from_token")
    def test_get_team_from_request_fallback_to_get_token(self, mock_get_team_from_token, mock_get_token):
        """Test _get_team_from_request falls back to get_token when no explicit token in request body."""
        # Setup mocks
        mock_team = Mock()
        mock_get_team_from_token.return_value = mock_team
        mock_get_token.return_value = "fallback_token"

        # Create request without explicit project_api_key
        request = self.factory.post("/test/", [{"data": "bulk_data"}], format="json")
        self.viewset.request = request

        # Mock _get_explicit_project_api_key to return None (bulk request)
        with patch.object(self.viewset, "_get_explicit_project_api_key", return_value=None):
            result = self.viewset._get_team_from_request()

        # Verify result and calls
        self.assertEqual(result, mock_team)
        mock_get_team_from_token.assert_called_once_with("fallback_token")
        mock_get_token.assert_called_once_with(None, request)

    @patch("posthog.api.routing.get_token")
    def test_get_team_from_request_no_token_found(self, mock_get_token):
        """Test _get_team_from_request returns None when no token is found."""
        # Setup mocks
        mock_get_token.return_value = None

        # Create request without any tokens
        request = self.factory.get("/test/")
        self.viewset.request = request

        result = self.viewset._get_team_from_request()

        # Verify result
        self.assertIsNone(result)
        mock_get_token.assert_called_once_with(None, request)

    @patch("posthog.api.routing.get_token")
    @patch("posthog.models.team.team.Team.objects.get_team_from_token")
    def test_get_team_from_request_authentication_failed(self, mock_get_team_from_token, mock_get_token):
        """Test _get_team_from_request raises AuthenticationFailed when token exists but team lookup fails."""
        from rest_framework.exceptions import AuthenticationFailed

        # Setup mocks
        mock_get_team_from_token.return_value = None  # No team found for token
        mock_get_token.return_value = "invalid_token"

        # Create request
        request = self.factory.post("/test/", {"other_data": "value"})
        self.viewset.request = request

        # Verify AuthenticationFailed is raised
        with self.assertRaises(AuthenticationFailed):
            self.viewset._get_team_from_request()
