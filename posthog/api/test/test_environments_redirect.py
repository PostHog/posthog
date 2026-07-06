import re
import json
from collections.abc import Iterable
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpResponse
from django.test import (
    Client as DjangoTestClient,
    SimpleTestCase,
    override_settings,
)
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.middleware import EnvironmentsRedirectMiddleware

# Tests for EnvironmentsRedirectMiddleware: /api/environments/* must 307-redirect to the
# equivalent /api/projects/* path (same id — Project ↔ primary Team are 1:1 and share it),
# preserving method, body, and query string. 307 (not 301/302) is load-bearing: a plain
# redirect lets clients downgrade writes to GET and drop the body. The redirect is gated
# by the `api-environments-redirect` feature flag, so tests patch the flag evaluation.
#
# Test clients follow the env→projects 307 like real HTTP clients and return the end
# response (see _follow_environments_redirect in posthog/test/base.py) — the classes
# asserting raw 307 semantics opt out via `client.follow_environments_redirect = False`.

ENVIRONMENTS_PREFIX = "api/environments"
PROJECTS_PREFIX = "api/projects"

# Resources with at least one /api/environments route that has no /api/projects counterpart
# yet. The middleware skips these (it only redirects paths that resolve project-side), so
# they keep working unredirected. Shrink this set by registering projects-side counterparts;
# do NOT grow it — new team-scoped endpoints must register under /api/projects.
# For `query` and `subscriptions` only specific sub-paths lack counterparts
# (query/<uuid>/progress and subscriptions/<id>/deliveries) — the rest of those
# resources is dual-registered and does redirect.
KNOWN_ENVIRONMENT_ONLY_RESOURCES = {
    "conversations",
    "core_memory",
    "max_hands_free",
    "max_tools",
    "mcp_analytics",
    "messaging",
    "progress",
    "property_access_controls",
    "query",
    "session_summaries",
    "subscriptions",
}


def _normalize_route(route: str) -> str:
    # Neutralize named-group names (parent_lookup_team_id vs parent_lookup_project_id)
    # and the `[^/.]+` lookup class BEFORE stripping anchors — a bare `^` strip would
    # corrupt the character class — so structurally identical routes compare equal.
    route = re.sub(r"\(\?P<[^>]+>", "(", route)
    route = route.replace("[^/.]+", "[param]")
    return route.replace("^", "").replace("$", "")


def _collect_routes_under(prefix: str) -> set[str]:
    collected: set[str] = set()

    def walk(patterns: Iterable, base: str) -> None:
        for entry in patterns:
            pattern = base + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, pattern)
            elif isinstance(entry, URLPattern):
                collected.add(_normalize_route(pattern))

    walk(get_resolver().url_patterns, "")
    return {route for route in collected if route.startswith(prefix)}


def _resource_of(route_suffix: str) -> str:
    # Route suffixes look like "/([/.]+)/dashboards/..." or "/<int:team_id>/progress/" —
    # the resource is the first literal segment after the team id parameter.
    segments = route_suffix.lstrip("/").split("/")
    if len(segments) < 2:
        return ""
    match = re.match(r"\w+", segments[1])
    return match.group(0) if match else segments[1]


class TestEveryEnvironmentsRouteHasAProjectsCounterpart(APIBaseTest):
    def test_environment_only_routes_are_known(self):
        # The middleware only redirects paths whose rewritten /api/projects form resolves,
        # so an unknown env-only route can't 404 — but it also silently won't redirect.
        # This pins the gap so it shrinks deliberately instead of growing unnoticed.
        env_routes = {r.removeprefix(ENVIRONMENTS_PREFIX) for r in _collect_routes_under(ENVIRONMENTS_PREFIX)}
        project_routes = {r.removeprefix(PROJECTS_PREFIX) for r in _collect_routes_under(PROJECTS_PREFIX)}
        unknown = {_resource_of(r) for r in env_routes - project_routes} - KNOWN_ENVIRONMENT_ONLY_RESOURCES
        self.assertEqual(
            unknown,
            set(),
            "new /api/environments routes without a /api/projects counterpart — register them "
            f"under /api/projects (see posthog/api/rest_router.py) instead of env-only: {sorted(unknown)}",
        )


class TestFlagDistinctId(SimpleTestCase):
    # The distinct id fed to the flag is what makes the rollout incremental: a per-team id
    # buckets by team, the constant id rides the global switch. If id extraction regresses,
    # numeric-team paths silently fall back to the constant and the flag becomes a kill
    # switch again — these cases catch that (and the reverse: @current must NOT get a team id).
    @parameterized.expand(
        [
            (
                "numeric id buckets per team",
                "/api/environments/123/feature_flags/",
                "environments_api_redirect:team:123",
            ),
            ("numeric id no trailing slash", "/api/environments/42", "environments_api_redirect:team:42"),
            (
                "current alias falls back to constant",
                "/api/environments/@current/insights/",
                "environments_api_redirect",
            ),
            ("non-numeric id falls back to constant", "/api/environments/abc/foo/", "environments_api_redirect"),
            ("keyless path falls back to constant", "/api/environments", "environments_api_redirect"),
        ]
    )
    def test_flag_distinct_id(self, _name: str, path: str, expected: str) -> None:
        self.assertEqual(EnvironmentsRedirectMiddleware._flag_distinct_id(path), expected)


class TestEnvironmentsRedirect(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.follow_environments_redirect = False  # type: ignore[attr-defined] # raw 307 assertions
        flag_patcher = patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def assert_redirected(self, path: str, expected_location: str, method: str = "GET") -> HttpResponse:
        # cast: the DRF stubs type APIClient.generic via the request-factory side, but at
        # runtime the client returns the response.
        response = cast(HttpResponse, self.client.generic(method, path))
        self.assertEqual(
            response.status_code,
            status.HTTP_307_TEMPORARY_REDIRECT,
            f"{method} {path} should 307-redirect, got {response.status_code}",
        )
        self.assertEqual(response["Location"], expected_location)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn(f"<{expected_location}>", response["Link"])
        self.assertIn('rel="successor-version"', response["Link"])
        return response

    @parameterized.expand(["GET", "POST", "PATCH", "PUT", "DELETE"])
    def test_detail_redirects_preserving_method(self, method: str):
        self.assert_redirected(f"/api/environments/{self.team.id}/", f"/api/projects/{self.team.id}/", method)

    @parameterized.expand(["GET", "POST"])
    def test_root_list_redirects_preserving_method(self, method: str):
        self.assert_redirected("/api/environments/", "/api/projects/", method)

    def test_current_alias_redirects(self):
        self.assert_redirected("/api/environments/@current/", "/api/projects/@current/")

    def test_nested_resource_redirects(self):
        self.assert_redirected(
            f"/api/environments/{self.team.id}/dashboards/", f"/api/projects/{self.team.id}/dashboards/", "POST"
        )

    def test_action_redirects_with_query_string(self):
        self.assert_redirected(
            f"/api/environments/{self.team.id}/settings_as_of/?at=2026-01-01T00:00:00Z",
            f"/api/projects/{self.team.id}/settings_as_of/?at=2026-01-01T00:00:00Z",
        )

    def test_query_string_is_preserved(self):
        self.assert_redirected(
            "/api/environments/@current/?limit=10&offset=5&search=a%20b",
            "/api/projects/@current/?limit=10&offset=5&search=a%20b",
        )

    def test_followed_patch_reaches_projects_endpoint_with_body_intact(self):
        # The Django test client preserves method and body across 307, like real clients do —
        # this proves a write round-trips through the redirect end to end.
        response = self.client.patch(
            "/api/environments/@current/",
            data=json.dumps({"name": "Renamed via redirect"}),
            content_type="application/json",
            follow=True,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.redirect_chain, [("/api/projects/@current/", status.HTTP_307_TEMPORARY_REDIRECT)])
        self.assertEqual(response.json()["name"], "Renamed via redirect")
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Renamed via redirect")

    def test_projects_paths_are_not_redirected(self):
        response = self.client.get(f"/api/projects/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("Deprecation", response.headers)

    def test_nested_projects_environments_path_is_not_redirected(self):
        # The deprecated nested route /api/projects/:id/environments/ must not loop.
        response = self.client.get(f"/api/projects/{self.team.id}/environments/")
        self.assertNotEqual(response.status_code, status.HTTP_307_TEMPORARY_REDIRECT)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn("Deprecation", response.headers)

    def test_environment_only_route_passes_through_unredirected(self):
        # /api/environments/:id/progress/ has no /api/projects counterpart yet — it must
        # keep working and must not advertise a successor path that would 404.
        response = self.client.get(f"/api/environments/{self.team.id}/progress/")
        self.assertNotEqual(response.status_code, status.HTTP_307_TEMPORARY_REDIRECT)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn("Deprecation", response.headers)

    def test_similarly_prefixed_paths_are_not_redirected(self):
        response = self.client.get("/api/environments_lookalike/")
        self.assertNotEqual(response.status_code, status.HTTP_307_TEMPORARY_REDIRECT)
        self.assertNotIn("Deprecation", response.headers)


class TestDefaultTestClientFollowsRedirect(APIBaseTest):
    # Uses the default (following) client: when the redirect is on, tests across the
    # repo must receive the end response, not the 307.

    def test_read_through_redirect_returns_end_response(self):
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True):
            response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.team.id)

    def test_write_through_redirect_preserves_method_and_body(self):
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True):
            response = self.client.patch(f"/api/environments/{self.team.id}/", {"name": "Followed end to end"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["name"], "Followed end to end")

    def test_unrelated_feature_flag_mocks_still_get_end_responses(self):
        # Many tests blanket-mock feature_enabled for their own flags, which turns the
        # redirect on as a side effect — they must keep getting end codes, not 307s
        # (this broke product test suites in CI).
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_hand_built_clients_also_follow(self):
        # Product suites instantiate APIClient()/Client() directly instead of using
        # APIBaseTest's client — the follow behavior is patched onto the classes, so
        # those clients must follow too.
        drf_client = APIClient()
        drf_client.force_login(self.user)
        django_client = DjangoTestClient()
        django_client.force_login(self.user)
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True):
            for client in (drf_client, django_client):
                response = client.get(f"/api/environments/{self.team.id}/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestEnvironmentsRedirectKillSwitch(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.follow_environments_redirect = False  # type: ignore[attr-defined] # raw 307 assertions

    def test_redirect_is_off_by_default_but_deprecation_headers_are_present(self):
        # No patch: the analytics SDK is disabled under TEST, so the flag evaluates to
        # None — the redirect must fail closed while deprecation headers still ship.
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn(f"</api/projects/{self.team.id}/>", response["Link"])
        self.assertIn("Sunset", response.headers)

    def test_flag_toggles_redirect_without_restart(self):
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True):
            self.assert_redirect_enabled()
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=False):
            response = self.client.get(f"/api/environments/{self.team.id}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        with patch.object(EnvironmentsRedirectMiddleware, "_redirect_enabled", return_value=True):
            self.assert_redirect_enabled()

    def test_flag_is_evaluated_locally_without_emitting_events(self):
        with override_settings(TEST=False), patch("posthoganalytics.feature_enabled", return_value=True) as flag_eval:
            self.assertTrue(EnvironmentsRedirectMiddleware._redirect_enabled())
        flag_eval.assert_called_once_with(
            "api-environments-redirect",
            "environments_api_redirect",
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    def assert_redirect_enabled(self) -> None:
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_307_TEMPORARY_REDIRECT)

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="2026-07-31")
    def test_sunset_header_is_http_date(self):
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response["Sunset"], "Fri, 31 Jul 2026 00:00:00 GMT")

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="")
    def test_sunset_header_is_omitted_when_unset(self):
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertNotIn("Sunset", response.headers)
