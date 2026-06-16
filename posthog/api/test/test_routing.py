import random
import pathlib
import importlib
import importlib.util
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.apps import apps
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import DefaultRouterPlusPlus, RouterRegistry, TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.scoping import get_current_team_id
from posthog.models.team.team import Team
from posthog.permissions import APIScopePermission

from products.annotations.backend.api.annotation import AnnotationSerializer
from products.annotations.backend.models.annotation import Annotation


class FooViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer

    @action(detail=False, methods=["get"])
    def current_scope(self, request, **kwargs):
        return Response({"team_id": get_current_team_id()})


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


@override_settings(ROOT_URLCONF=__name__)
class TestTeamAndOrgViewSetMixinSpanTagging(APIBaseTest):
    """The request (root) span should be tagged with team_id for team/project views."""

    def _recording_tracer(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return provider.get_tracer("test"), exporter

    def _root_span(self, exporter):
        spans = [s for s in exporter.get_finished_spans() if s.name == "test-request-root"]
        self.assertEqual(len(spans), 1)
        return spans[0]

    def test_team_view_tags_request_span_with_team_id(self):
        tracer, exporter = self._recording_tracer()
        with tracer.start_as_current_span("test-request-root"):
            response = self.client.get(f"/api/environments/{self.team.id}/foos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._root_span(exporter).attributes["team_id"], self.team.id)

    def test_organization_view_does_not_tag_team_id(self):
        # Org-scoped views have no single team, so the stamp must not fire.
        tracer, exporter = self._recording_tracer()
        with tracer.start_as_current_span("test-request-root"):
            response = self.client.get(f"/api/organizations/{self.organization.id}/foos/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("team_id", self._root_span(exporter).attributes or {})


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

    def test_team_scope_context_set_from_url_team_not_user_current_team(self):
        # User's "current" team is set to self.team, but the URL targets another
        # team in the same org. The team scope context inside the view must reflect
        # the URL's team, not user.current_team_id (otherwise queries would silently
        # mismatch — same class of bug as #50899).
        other_team = Team.objects.create(organization=self.organization, project=self.project)
        self.user.current_team = self.team
        self.user.save()

        # Capture the scope before the request — `dispatch()` resets via
        # ContextVar.reset(token), which restores whatever was in scope before
        # the view fired. Some test runners may have leftover scope from
        # earlier tests on the same thread; we just assert the wrapper
        # restored the pre-request value, not unconditionally None.
        pre_request_scope = get_current_team_id()

        response = self.client.get(f"/api/environments/{other_team.id}/foos/current_scope/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team_id"], other_team.id)
        self.assertEqual(get_current_team_id(), pre_request_scope)

    def test_team_scope_context_set_from_url_for_project_view(self):
        response = self.client.get(f"/api/projects/{self.team.id}/foos/current_scope/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team_id"], self.team.id)

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


@override_settings(ROOT_URLCONF=__name__)
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
            headers={"authorization": f"Bearer {self.access_token.token}"},
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
            headers={"authorization": f"Bearer {self.access_token.token}"},
        )

        # Should not have access to other org's team (self.user is not a member of other_org)
        self.assertEqual(response.status_code, 403)

    def test_oauth_token_can_access_organization_resources(self):
        """Test that OAuth tokens can access organization-scoped resources"""
        Annotation.objects.create(team=self.team, organization=self.organization)

        response = self.client.get(
            f"/api/scoped_organizations/{self.organization.id}/scoped_foos/",
            headers={"authorization": f"Bearer {self.access_token.token}"},
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
            headers={"authorization": f"Bearer {expired_token.token}"},
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
            headers={"authorization": f"Bearer {self.access_token.token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)


def test_router_registry_add_returns_item_and_resolves_by_name():
    registry = RouterRegistry()
    item = DefaultRouterPlusPlus().register(r"things", FooViewSet, "things")
    assert registry.add("things", item) is item
    assert registry.get("things") is item


def test_router_registry_rejects_duplicate_name():
    registry = RouterRegistry()
    item = DefaultRouterPlusPlus().register(r"things", FooViewSet, "things")
    registry.add("things", item)
    with pytest.raises(ValueError):
        registry.add("things", item)


def test_router_registry_get_unknown_name_lists_known():
    registry = RouterRegistry()
    registry.add("things", DefaultRouterPlusPlus().register(r"things", FooViewSet, "things"))
    with pytest.raises(KeyError, match="things"):
        registry.get("missing")


def _registry_with_parents():
    registry = RouterRegistry()
    root = DefaultRouterPlusPlus()
    registry.set_root(root)
    registry.add("projects", root.register(r"projects", FooViewSet, "projects"))
    registry.add("environments", root.register(r"environments", FooViewSet, "environments"))
    return registry


def test_register_legacy_dual_route_registers_both_surfaces():
    registry = _registry_with_parents()
    project_item, environment_item = registry.register_legacy_dual_route(
        r"things", FooViewSet, "project_things", ["team_id"]
    )
    assert project_item is not None
    assert environment_item is not None


@pytest.mark.parametrize(
    "basename,lookups,match",
    [
        ("project_things", [], "non-empty"),
        ("project_things", ["project_id"], "team_id"),
        ("things", ["team_id"], "must start with"),
    ],
)
def test_register_legacy_dual_route_rejects_bad_input(basename, lookups, match):
    registry = _registry_with_parents()
    with pytest.raises(ValueError, match=match):
        registry.register_legacy_dual_route(r"things", FooViewSet, basename, lookups)


# --- Product route auto-discovery -----------------------------------------------------
# Mirrors the discovery loop in posthog/api/__init__.py so the tests exercise the same
# filter (products.* app whose `.routes` module exists).


def _discover_product_route_modules():
    modules = []
    for app_config in apps.get_app_configs():
        if not app_config.name.startswith("products."):
            continue
        module_name = f"{app_config.name}.routes"
        if importlib.util.find_spec(module_name) is None:
            continue
        modules.append(importlib.import_module(module_name))
    return modules


def _build_product_routes(modules):
    router = DefaultRouterPlusPlus()
    registry = RouterRegistry()
    registry.set_root(router)
    registry.add("projects", router.register(r"projects", FooViewSet, "projects"))
    registry.add("environments", router.register(r"environments", FooViewSet, "environments"))
    registry.add("organizations", router.register(r"organizations", FooViewSet, "organizations"))
    for module in modules:
        module.register_routes(registry)
    return router


def _url_signature(router):
    return sorted((str(pattern.pattern), pattern.name) for pattern in router.urls)


def _iter_router_viewset_actions(router):
    for pattern in router.urls:
        callback = getattr(pattern, "callback", None)
        viewset_class = getattr(callback, "cls", None)
        actions = getattr(callback, "actions", None)
        if viewset_class is None or actions is None:
            continue
        yield pattern.name, viewset_class, set(actions.values())


def test_product_route_discovery_is_order_independent():
    modules = _discover_product_route_modules()
    assert modules, "expected to discover product route modules"
    in_order = _url_signature(_build_product_routes(modules))
    shuffled = modules[:]
    random.Random(20240601).shuffle(shuffled)
    out_of_order = _url_signature(_build_product_routes(shuffled))
    assert in_order == out_of_order


def test_discovery_covers_every_product_with_a_routes_module():
    # Every routes.py on disk must be reachable through INSTALLED_APPS, otherwise the loop
    # would silently drop it. parents[3] of .../posthog/api/test/test_routing.py is the repo root.
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    on_disk = {
        f"products.{path.parent.parent.name}.backend.routes" for path in repo_root.glob("products/*/backend/routes.py")
    }
    discovered = {module.__name__ for module in _discover_product_route_modules()}
    assert discovered == on_disk


def test_every_discovered_routes_module_is_callable():
    modules = _discover_product_route_modules()
    missing = [m.__name__ for m in modules if not callable(getattr(m, "register_routes", None))]
    assert not missing, f"routes modules without a register_routes callable: {missing}"


def test_project_secret_api_key_authentication_routes_include_api_scope_permission():
    from posthog.api import router

    _assert_project_secret_api_key_routes_include_api_scope_permission(router)


def _assert_project_secret_api_key_routes_include_api_scope_permission(router):
    missing = []
    authenticator = ProjectSecretAPIKeyAuthentication()
    for route_name, viewset_class, actions in _iter_router_viewset_actions(router):
        if ProjectSecretAPIKeyAuthentication not in viewset_class.authentication_classes:
            continue

        for action_name in actions:
            view = viewset_class()
            view.action = action_name
            view.request = type("Request", (), {"successful_authenticator": authenticator})()
            view.kwargs = {}
            permissions = view.get_permissions()
            if not any(isinstance(permission, APIScopePermission) for permission in permissions):
                missing.append(f"{route_name}:{viewset_class.__name__}.{action_name}")

    assert not missing, (
        "ProjectSecretAPIKeyAuthentication routes must include APIScopePermission from get_permissions(): "
        + ", ".join(sorted(missing))
    )


def test_project_secret_api_key_route_contract_fails_without_api_scope_permission():
    class MisconfiguredPSAKViewSet(viewsets.GenericViewSet):
        authentication_classes = [ProjectSecretAPIKeyAuthentication]

        def list(self, request):
            return Response({})

    router = DefaultRouterPlusPlus()
    router.register(r"misconfigured-psak", MisconfiguredPSAKViewSet, "misconfigured_psak")

    with pytest.raises(AssertionError, match="misconfigured_psak-list:MisconfiguredPSAKViewSet.list"):
        _assert_project_secret_api_key_routes_include_api_scope_permission(router)


def test_project_secret_api_key_route_contract_passes_with_team_and_org_mixin():
    class ConfiguredPSAKViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
        authentication_classes = [ProjectSecretAPIKeyAuthentication]
        scope_object = "endpoint"

        def list(self, request):
            return Response({})

    router = DefaultRouterPlusPlus()
    router.register(r"configured-psak", ConfiguredPSAKViewSet, "configured_psak")

    _assert_project_secret_api_key_routes_include_api_scope_permission(router)


def test_router_registry_add_rejects_products_caller():
    registry = RouterRegistry()
    item = DefaultRouterPlusPlus().register(r"things", FooViewSet, "things")
    # Give the calling frame a products.* __name__ so the guard sees a product caller.
    namespace = {"registry": registry, "item": item, "__name__": "products.fake.backend.routes"}
    source = "def _caller():\n    registry.add('things', item)\n_caller()"
    with pytest.raises(RuntimeError, match="core-owned"):
        exec(compile(source, "products/fake/backend/routes.py", "exec"), namespace)
