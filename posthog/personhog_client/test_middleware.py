from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.personhog_client.interceptor import get_caller_tag
from posthog.personhog_client.middleware import PersonHogCallerTagMiddleware, _resolve_caller_tag


class TestResolveCallerTag(SimpleTestCase):
    @parameterized.expand(
        [
            ("persons_list", "/api/environments/1/persons/", "api/persons"),
            ("legacy_persons", "/api/person/", "api/persons"),
            ("cohorts_list", "/api/projects/1/cohorts/", "api/cohorts"),
            ("legacy_cohort", "/api/cohort/", "api/cohorts"),
            ("feature_flags", "/api/projects/1/feature_flags/", "api/feature-flags"),
            ("groups", "/api/environments/1/groups/", "api/groups"),
            ("insights", "/api/projects/1/insights/", "api/insights"),
            ("dashboards", "/api/projects/1/dashboards/", "api/dashboards"),
            ("events", "/api/environments/1/events/", "api/events"),
            ("query", "/api/projects/1/query/", "api/query"),
        ]
    )
    def test_known_routes(self, _name: str, path: str, expected_tag: str) -> None:
        factory = RequestFactory()
        request = factory.get(path)
        self.assertEqual(_resolve_caller_tag(request), expected_tag)

    def test_unmapped_api_route_falls_back(self) -> None:
        factory = RequestFactory()
        request = factory.get("/api/projects/1/annotations/")
        self.assertEqual(_resolve_caller_tag(request), "api/other")

    def test_non_api_route_falls_back(self) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        self.assertEqual(_resolve_caller_tag(request), "web/other")

    def test_spa_catchall_path(self) -> None:
        factory = RequestFactory()
        request = factory.get("/this/path/does/not/exist/ever/")
        self.assertEqual(_resolve_caller_tag(request), "web/other")


class TestPersonHogCallerTagMiddleware(SimpleTestCase):
    def test_sets_and_resets_caller_tag(self) -> None:
        factory = RequestFactory()
        request = factory.get("/api/projects/1/cohorts/")
        observed_tags: list[str] = []

        def fake_response(req):
            observed_tags.append(get_caller_tag())
            return HttpResponse("ok")

        middleware = PersonHogCallerTagMiddleware(fake_response)
        middleware(request)

        self.assertEqual(observed_tags, ["api/cohorts"])
        self.assertEqual(get_caller_tag(), "unknown")

    def test_resets_on_exception(self) -> None:
        factory = RequestFactory()
        request = factory.get("/api/projects/1/feature_flags/")

        def exploding_response(req):
            raise ValueError("boom")

        middleware = PersonHogCallerTagMiddleware(exploding_response)

        with self.assertRaises(ValueError):
            middleware(request)

        self.assertEqual(get_caller_tag(), "unknown")
