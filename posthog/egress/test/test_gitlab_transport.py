from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.gitlab.transport import gitlab_request, token_scope

_TOKEN = "glpat-not-a-real-token"
_URL = "https://gitlab.example.com/api/v4/projects/7/merge_requests"


def _response(headers: dict[str, str]) -> requests.Response:
    response = requests.Response()
    response.status_code = 201
    response.headers.update(headers)
    return response


def _gitlab_samples() -> list:
    return [
        sample for metric in REGISTRY.collect() if metric.name.startswith("gitlab_api") for sample in metric.samples
    ]


class TestGitLabTransport(SimpleTestCase):
    def test_the_token_is_sent_as_a_header_and_never_reaches_a_label(self) -> None:
        with patch("requests.request", return_value=_response({})) as request:
            gitlab_request(
                "POST", _URL, token=_TOKEN, source="integration", endpoint="/api/v4/projects/{id}/merge_requests"
            )

        assert request.call_args.kwargs["headers"]["PRIVATE-TOKEN"] == _TOKEN
        assert not any(_TOKEN in value for sample in _gitlab_samples() for value in sample.labels.values())

    @parameterized.expand(
        [
            ("documented_name", "throttle_authenticated_api", "throttle_authenticated_api"),
            # A self-managed instance controls this header, so a value GitLab does not document must
            # not become a label value, whether or not it is shaped like a throttle name.
            ("undocumented_name", "throttle_made_up_by_the_server", "unknown"),
            ("unexpected_name", "Some Proxy/1.0", "unknown"),
        ]
    )
    def test_rate_limit_headers_feed_the_gauges(self, _name: str, throttle: str, resource: str) -> None:
        headers = {
            "RateLimit-Name": throttle,
            "RateLimit-Limit": "2000",
            "RateLimit-Remaining": "1990",
            "RateLimit-Reset": "1609844400",
        }
        with patch("requests.request", return_value=_response(headers)):
            gitlab_request(
                "POST", _URL, token=_TOKEN, source="integration", endpoint="/api/v4/projects/{id}/merge_requests"
            )

        labels = {"scope": token_scope(_URL, _TOKEN), "resource": resource}
        assert REGISTRY.get_sample_value("gitlab_api_rate_limit_remaining", labels) == 1990
        assert REGISTRY.get_sample_value("gitlab_api_rate_limit_reset_timestamp_seconds", labels) == 1609844400
