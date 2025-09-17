import pytest
from posthog.test.base import APIBaseTest

from django.test import override_settings
from django.urls import include, path

from rest_framework import viewsets

from posthog.api.annotation import AnnotationSerializer
from posthog.api.routing import DefaultRouterPlusPlus, TeamAndOrgViewSetMixin
from posthog.models.annotation import Annotation
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team.team import Team


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
