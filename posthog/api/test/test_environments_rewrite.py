from posthog.test.base import APIBaseTest

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from rest_framework import status

from posthog.middleware import EnvironmentsRewriteMiddleware

# EnvironmentsRewriteMiddleware serves /api/environments/* through the equivalent /api/projects/*
# viewset (same id — Project ↔ primary Team are 1:1 and share it) via an in-process path rewrite.
# The rewrite is unconditional (there are no /api/environments/* routes left to fall back to) and
# deliberately not a 307/308 — many API clients don't follow redirects — so the client gets a normal
# 200 on the original URL with method, body, and query string intact.


class TestRewriteMechanism(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _run(self, path, query_string=""):
        seen = {}

        def get_response(request):
            # Capture the path the downstream sees — that's what URL resolution routes on.
            seen["path"] = request.path
            seen["path_info"] = request.path_info
            return HttpResponse("ok")

        request = self.factory.get(path, QUERY_STRING=query_string)
        response = EnvironmentsRewriteMiddleware(get_response)(request)
        return seen, response

    def test_env_path_with_projects_counterpart_is_rewritten(self):
        seen, response = self._run("/api/environments/@current/")
        # Downstream resolves against /api/projects, not the original /api/environments path.
        self.assertEqual(seen["path"], "/api/projects/@current/")
        self.assertEqual(seen["path_info"], "/api/projects/@current/")
        self.assertEqual(response["Deprecation"], "true")
        self.assertEqual(response["Link"], '</api/projects/@current/>; rel="successor-version"')

    def test_successor_link_preserves_query_string(self):
        _, response = self._run("/api/environments/@current/", query_string="format=json")
        self.assertEqual(response["Link"], '</api/projects/@current/?format=json>; rel="successor-version"')

    def test_env_path_without_projects_counterpart_is_not_rewritten(self):
        # No /api/projects counterpart — the rewrite is skipped and no deprecation headers are added.
        seen, response = self._run("/api/environments/@current/does_not_exist_anywhere/")
        self.assertEqual(seen["path"], "/api/environments/@current/does_not_exist_anywhere/")
        self.assertNotIn("Deprecation", response)

    def test_non_environments_path_is_untouched(self):
        seen, response = self._run("/api/projects/@current/")
        self.assertEqual(seen["path"], "/api/projects/@current/")
        self.assertNotIn("Deprecation", response)


class TestEnvironmentsRewriteIntegration(APIBaseTest):
    def test_read_is_served_transparently_with_deprecation_headers(self):
        response = self.client.get("/api/environments/@current/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # No redirect — the client gets the response on the original URL.
        self.assertNotIn("Location", response)
        self.assertEqual(response["Deprecation"], "true")
        self.assertEqual(response["Link"], '</api/projects/@current/>; rel="successor-version"')

    def test_write_round_trips_method_and_body(self):
        response = self.client.patch("/api/environments/@current/", {"name": "renamed via env alias"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "renamed via env alias")


class TestSunsetHeader(SimpleTestCase):
    def _sunset(self):
        def get_response(request):
            return HttpResponse("ok")

        request = RequestFactory().get("/api/environments/@current/")
        return EnvironmentsRewriteMiddleware(get_response)(request).get("Sunset")

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="2026-07-31")
    def test_sunset_header_is_an_http_date(self):
        self.assertEqual(self._sunset(), "Fri, 31 Jul 2026 00:00:00 GMT")

    @override_settings(API_ENVIRONMENTS_SUNSET_DATE="")
    def test_sunset_header_is_omitted_when_unset(self):
        self.assertIsNone(self._sunset())
