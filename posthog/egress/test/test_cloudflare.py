import json
from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.cloudflare.client import MAX_URLS_PER_PURGE, CloudflarePurgeFailed, purge_urls
from posthog.egress.cloudflare.limiter import cloudflare_account_key
from posthog.egress.limiter.policies import resolve_policy

_FAKE_TOKEN = "fake-token-for-tests"
_ZONE_ID = "zone-for-tests"
_ACCEPTED = json.dumps({"success": True, "errors": [], "messages": [], "result": {"id": "purge-id"}})


def _response(status: int, body: str) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = body.encode()
    return response


@contextmanager
def _cloudflare_answers(response: requests.Response) -> Iterator[MagicMock]:
    with (
        patch("posthog.egress.cloudflare.transport.consume_cloudflare_sync", return_value=True),
        patch("requests.request", return_value=response) as request,
    ):
        yield request


class TestCloudflarePurge(SimpleTestCase):
    def test_purge_sends_the_request_shape_cloudflare_documents(self) -> None:
        with _cloudflare_answers(_response(200, _ACCEPTED)) as request:
            purge_urls(
                ["https://media.example.com/uploaded_media/1"], zone_id=_ZONE_ID, api_token=_FAKE_TOKEN, source="test"
            )

        assert request.call_args.args == ("POST", f"https://api.cloudflare.com/client/v4/zones/{_ZONE_ID}/purge_cache")
        kwargs = request.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_TOKEN}"
        assert kwargs["json"] == {"files": ["https://media.example.com/uploaded_media/1"]}

    def test_purge_splits_urls_into_requests_cloudflare_accepts(self) -> None:
        urls = [f"https://media.example.com/uploaded_media/{index}" for index in range(MAX_URLS_PER_PURGE + 1)]
        with _cloudflare_answers(_response(200, _ACCEPTED)) as request:
            purge_urls(urls, zone_id=_ZONE_ID, api_token=_FAKE_TOKEN, source="test")

        assert [len(call.kwargs["json"]["files"]) for call in request.call_args_list] == [MAX_URLS_PER_PURGE, 1]

    @parameterized.expand(
        [
            ("rate_limited", 429, json.dumps({"success": False, "errors": [{"code": 1134}], "result": None})),
            ("unsuccessful_body", 200, json.dumps({"success": False, "errors": [{"code": 1134}], "result": None})),
            ("non_json_body", 502, "<html>bad gateway</html>"),
        ]
    )
    def test_purge_raises_when_cloudflare_does_not_accept_it(self, _name: str, status: int, body: str) -> None:
        with _cloudflare_answers(_response(status, body)), self.assertRaises(CloudflarePurgeFailed):
            purge_urls(
                ["https://media.example.com/uploaded_media/1"], zone_id=_ZONE_ID, api_token=_FAKE_TOKEN, source="test"
            )

    @override_settings(CLOUDFLARE_EGRESS_PER_MINUTE_BUDGET=7, CLOUDFLARE_EGRESS_HOURLY_BUDGET=11)
    def test_budgets_come_from_the_settings_they_are_named_after(self) -> None:
        assert resolve_policy(cloudflare_account_key()).limits == ((7, 60.0), (11, 3600.0))
