from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from prometheus_client import REGISTRY

from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.vapi.transport import vapi_request


def _request_count(scope: str, status_code: str = "201") -> float:
    labels = {
        "scope": scope,
        "method": "POST",
        "endpoint": "/call/web",
        "status_code": status_code,
        "source": "user_interviews",
    }
    return REGISTRY.get_sample_value("vapi_api_requests_total", labels) or 0


class TestVapiTransport(SimpleTestCase):
    def test_request_keeps_the_token_in_the_header_and_out_of_the_metric_scope(self) -> None:
        response = requests.Response()
        response.status_code = 201
        fingerprint = scope_fingerprint("pk_test")
        before = _request_count(fingerprint)

        with patch("requests.request", return_value=response) as request:
            vapi_request(
                "POST",
                "https://api.vapi.ai/call/web",
                api_token="pk_test",
                source="user_interviews",
                endpoint="/call/web",
                json={"assistantId": "assistant"},
            )

        assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer pk_test"
        assert _request_count(fingerprint) == before + 1
        assert _request_count("pk_test") == 0

    def test_a_request_that_raises_is_recorded_and_re_raised(self) -> None:
        fingerprint = scope_fingerprint("pk_test")
        before = _request_count(fingerprint, "exception")

        with patch("requests.request", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(requests.ConnectionError):
                vapi_request(
                    "POST",
                    "https://api.vapi.ai/call/web",
                    api_token="pk_test",
                    source="user_interviews",
                    endpoint="/call/web",
                )

        assert _request_count(fingerprint, "exception") == before + 1
