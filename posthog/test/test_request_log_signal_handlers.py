from typing import Any, cast

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from django_structlog.middlewares import RequestMiddleware
from parameterized import parameterized

from posthog.request_log_signal_handlers import redact_credential_query_params


class TestRequestLogSignalHandlers(SimpleTestCase):
    def test_request_logging_redacts_api_key_query_param(self) -> None:
        middleware = RequestMiddleware(lambda request: HttpResponse())
        request = RequestFactory().get("/api/projects/", {"personal_api_key": "phx_testvalue", "limit": "10"})

        with self.assertLogs("django_structlog.middlewares.request", level="INFO") as logs:
            middleware(request)

        event_dicts = [cast(dict[str, Any], record.msg) for record in logs.records]
        assert [(event_dict["event"], event_dict["request"]) for event_dict in event_dicts] == [
            ("request_started", "GET /api/projects/?personal_api_key=<redacted>&limit=10"),
            ("request_finished", "GET /api/projects/?personal_api_key=<redacted>&limit=10"),
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
