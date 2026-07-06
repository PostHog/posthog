import re
from collections.abc import Iterable

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from parameterized import parameterized
from rest_framework import status

from posthog.middleware import EnvironmentsRewriteMiddleware

# Tests for EnvironmentsRewriteMiddleware: /api/environments/* is served through the
# equivalent /api/projects/* viewset (same id — Project ↔ primary Team are 1:1 and share
# it) via an in-process path rewrite, gated by the `api-environments-redirect` flag. The
# rewrite is deliberately not a 307/308 — many API clients don't follow redirects — so the
# client gets a normal 200 on the original URL with method, body, and query string intact.

ENVIRONMENTS_PREFIX = "api/environments"
PROJECTS_PREFIX = "api/projects"

# Resources with at least one /api/environments route that has no /api/projects counterpart
# yet. The middleware skips these (it only rewrites paths that resolve project-side), so
# they keep working via the legacy route. Shrink this set by registering projects-side
# counterparts; do NOT grow it — new team-scoped endpoints must register under /api/projects.
# Only a few sub-paths still lack a counterpart: messaging/customerio/webhook, a bare
# progress endpoint, and query/<uuid>/progress — everything else is dual-registered.
KNOWN_ENVIRONMENT_ONLY_RESOURCES = {
    "messaging",
    "progress",
    "query",
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
        # The middleware only rewrites paths whose /api/projects form resolves, so an
        # unknown env-only route can't 404 — but it also silently won't be rewritten.
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
        self.assertEqual(EnvironmentsRewriteMiddleware._flag_distinct_id(path), expected)


class TestRewriteMechanism(SimpleTestCase):
    # The rewrite mutating the request path to /api/projects is the one signal that would go
    # silent if it regressed: because both prefixes are dual-registered, an end-to-end request
    # would still return 200 via the legacy route even if the rewrite did nothing. This asserts
    # the path the downstream handler actually resolves.
    def _resolved_path(self, path: str, enabled: bool) -> str:
        captured: dict[str, str] = {}

        def get_response(request: HttpRequest) -> HttpResponse:
            captured["path"] = request.path
            captured["path_info"] = request.path_info
            return HttpResponse()

        request = RequestFactory().get(path)
        with patch.object(EnvironmentsRewriteMiddleware, "_rewrite_enabled", return_value=enabled):
            EnvironmentsRewriteMiddleware(get_response)(request)
        self.assertEqual(captured["path"], captured["path_info"])
        return captured["path"]

    @parameterized.expand(
        [
            ("dual route + enabled → projects", "/api/environments/2/dashboards/", True, "/api/projects/2/dashboards/"),
            (
                "dual route + disabled → unchanged",
                "/api/environments/2/dashboards/",
                False,
                "/api/environments/2/dashboards/",
            ),
            (
                "env-only route + enabled → unchanged",
                "/api/environments/2/progress/",
                True,
                "/api/environments/2/progress/",
            ),
            ("non-environments path → unchanged", "/api/projects/2/dashboards/", True, "/api/projects/2/dashboards/"),
        ]
    )
    def test_downstream_resolves_expected_path(self, _name: str, path: str, enabled: bool, expected: str) -> None:
        self.assertEqual(self._resolved_path(path, enabled), expected)


class TestEnvironmentsRewrite(APIBaseTest):
    def setUp(self):
        super().setUp()
        patcher = patch.object(EnvironmentsRewriteMiddleware, "_rewrite_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_is_served_transparently_without_a_redirect(self):
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(response.json()["id"], self.team.id)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn(f"</api/projects/{self.team.id}/>", response["Link"])
        self.assertIn('rel="successor-version"', response["Link"])

    def test_write_round_trips_method_and_body_without_a_redirect(self):
        # The point of the rewrite: a write to /api/environments applies on the same request,
        # so clients that don't follow 3xx (httpx, Guzzle) keep working.
        response = self.client.patch("/api/environments/@current/", {"name": "Renamed via rewrite"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(response.json()["name"], "Renamed via rewrite")
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Renamed via rewrite")

    def test_successor_link_includes_preserved_query_string(self):
        response = self.client.get(f"/api/environments/{self.team.id}/dashboards/?limit=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(f"</api/projects/{self.team.id}/dashboards/?limit=1>", response["Link"])

    def test_environment_only_route_is_not_rewritten_or_deprecated(self):
        # /progress/ has no /api/projects counterpart — served by the legacy route, and it
        # must not advertise a successor path that would 404.
        response = self.client.get(f"/api/environments/{self.team.id}/progress/")
        self.assertNotIn("Location", response.headers)
        self.assertNotIn("Deprecation", response.headers)

    @parameterized.expand(
        [
            ("projects path", "/api/projects/{team}/"),
            ("nested projects environments", "/api/projects/{team}/environments/"),
            ("similarly prefixed", "/api/environments_lookalike/"),
        ]
    )
    def test_paths_outside_the_environments_prefix_are_untouched(self, _name: str, path_template: str) -> None:
        response = self.client.get(path_template.format(team=self.team.id))
        self.assertNotIn("Deprecation", response.headers)
        self.assertNotIn("Location", response.headers)


class TestEnvironmentsRewriteFlag(APIBaseTest):
    def test_disabled_by_default_still_serves_and_advertises_successor(self):
        # SDK disabled under TEST → flag None → rewrite OFF, but the request must still
        # succeed (served by the legacy env route) and carry deprecation headers.
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn(f"</api/projects/{self.team.id}/>", response["Link"])
        self.assertIn("Sunset", response.headers)

    def test_blanket_feature_flag_mock_still_gets_a_transparent_response(self):
        # Product suites often mock feature_enabled=True for their own flags, which turns the
        # rewrite on as a side effect — they must keep getting a normal 200, never a redirect.
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("Location", response.headers)

    def test_flag_is_evaluated_locally_without_emitting_events(self):
        with override_settings(TEST=False), patch("posthoganalytics.feature_enabled", return_value=True) as flag_eval:
            self.assertTrue(EnvironmentsRewriteMiddleware._rewrite_enabled())
        flag_eval.assert_called_once_with(
            "api-environments-redirect",
            "environments_api_redirect",
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="2026-07-31")
    def test_sunset_header_is_http_date(self):
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertEqual(response["Sunset"], "Fri, 31 Jul 2026 00:00:00 GMT")

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="")
    def test_sunset_header_is_omitted_when_unset(self):
        response = self.client.get(f"/api/environments/{self.team.id}/")
        self.assertNotIn("Sunset", response.headers)
