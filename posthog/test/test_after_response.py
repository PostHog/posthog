from unittest import mock

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from rest_framework.request import Request

from posthog.after_response import AfterResponseMiddleware, run_after_response


class TestRunAfterResponse(SimpleTestCase):
    @parameterized.expand([("django_request", lambda request: request), ("drf_request", Request)])
    def test_runs_after_the_response_is_closed(self, _name, wrap):
        calls: list[str] = []

        def view(request: HttpRequest) -> HttpResponse:
            run_after_response(wrap(request), lambda: calls.append("after response"))
            calls.append("view")
            return HttpResponse()

        response = AfterResponseMiddleware(view)(RequestFactory().get("/"))
        assert calls == ["view"]

        response.close()
        assert calls == ["view", "after response"]

    def test_runs_at_once_outside_the_middleware(self):
        calls: list[str] = []

        run_after_response(RequestFactory().get("/"), lambda: calls.append("ran"))

        assert calls == ["ran"]

    def test_reports_a_failure_and_still_runs_the_rest(self):
        calls: list[str] = []
        error = ValueError("boom")

        def failing() -> None:
            raise error

        def view(request: HttpRequest) -> HttpResponse:
            run_after_response(request, failing)
            run_after_response(request, lambda: calls.append("second"))
            return HttpResponse()

        with mock.patch("posthog.after_response.capture_exception") as capture_exception:
            AfterResponseMiddleware(view)(RequestFactory().get("/")).close()

        capture_exception.assert_called_once_with(error)
        assert calls == ["second"]
