from typing import Any

from unittest.mock import patch

from django.core.signals import got_request_exception
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

import structlog
from django_structlog.middlewares import (
    RequestMiddleware,
    request as request_middleware,
)
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.request_log_signal_handlers import redact_credential_query_params


def _ok_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


def _failing_view(request: HttpRequest) -> HttpResponse:
    try:
        raise ValueError("boom")
    except ValueError:
        got_request_exception.send(sender=None, request=request)
    return HttpResponse(status=500)


class TestRequestLogSignalHandlers(SimpleTestCase):
    @parameterized.expand(
        [
            ("finished", _ok_view, "request_finished"),
            ("failed", _failing_view, "request_failed"),
        ]
    )
    def test_request_logging_redacts_api_key_query_param(self, _name: str, view: Any, final_event: str) -> None:
        middleware = RequestMiddleware(view)
        request = RequestFactory().get("/api/projects/", {"personal_api_key": "phx_testvalue", "limit": "10"})

        with (
            capture_logs() as event_dicts,
            patch.object(request_middleware, "logger", structlog.get_logger(request_middleware.__name__)),
        ):
            middleware(request)

        assert [(event_dict["event"], event_dict["request"]) for event_dict in event_dicts] == [
            ("request_started", "GET /api/projects/?personal_api_key=<redacted>&limit=10"),
            (final_event, "GET /api/projects/?personal_api_key=<redacted>&limit=10"),
        ]

    @parameterized.expand(
        [
            ("no_query", "GET /api/projects/", "GET /api/projects/"),
            ("unrelated_params", "GET /api/events/?limit=10&after=-1d", "GET /api/events/?limit=10&after=-1d"),
            (
                "every_credential_name",
                "GET /e/?token=phc_a&api_key=phc_b&access_token=pha_c&personal_api_key=phx_d",
                "GET /e/?token=<redacted>&api_key=<redacted>&access_token=<redacted>&personal_api_key=<redacted>",
            ),
            (
                "percent_encoded_name",
                "GET /api/projects/?personal%5Fapi%5Fkey=phx_abc",
                "GET /api/projects/?personal%5Fapi%5Fkey=<redacted>",
            ),
            (
                "mixed_case_name",
                "GET /api/projects/?Personal_Api_Key=phx_abc",
                "GET /api/projects/?Personal_Api_Key=<redacted>",
            ),
            ("repeated_param", "GET /e/?token=phc_a&token=phc_b", "GET /e/?token=<redacted>&token=<redacted>"),
            ("similar_name_kept", "GET /e/?token_type=bearer&tokens=3", "GET /e/?token_type=bearer&tokens=3"),
            ("name_without_value_kept", "GET /e/?token&limit=1", "GET /e/?token&limit=1"),
        ]
    )
    def test_redact_credential_query_params(self, _name: str, request_line: str, expected: str) -> None:
        assert redact_credential_query_params(request_line) == expected
