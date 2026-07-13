from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.github.transport import GitHubClient, github_request


def _response(status: int = 200) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({})
    prepared = requests.models.PreparedRequest()
    prepared.method = "GET"
    prepared.url = "https://api.github.com/search/code"
    response.request = prepared
    return response


class TestGitHubTransport(SimpleTestCase):
    @parameterized.expand(
        [
            ("code_search", "https://api.github.com/search/code?q=x", GitHubRateResource.CODE_SEARCH),
            ("core", "https://api.github.com/repos/o/r/pulls/1", GitHubRateResource.CORE),
        ]
    )
    def test_consume_routes_resource_by_url(self, _name: str, url: str, expected: GitHubRateResource) -> None:
        # The gate must charge each URL to the meter GitHub bills it against — the whole point of the
        # per-resource split. A regression here reverts /search/code to the core envelope.
        client = GitHubClient()
        with patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=True) as consume:
            client._consume("42", MagicMock(), "test", url)
        assert consume.call_args.kwargs["resource"] == expected

    def test_identity_blind_call_never_touches_the_limiter(self) -> None:
        # A None installation_id (public token / raw PAT) records volume only and must skip the gate,
        # or unrelated tokens would share and clobber one phantom budget.
        with (
            patch("posthog.egress.github.transport.consume_github_installation_sync") as consume,
            patch("requests.request", return_value=_response()),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request("GET", "https://api.github.com/search/code?q=x", source="test", installation_id=None)
        consume.assert_not_called()
