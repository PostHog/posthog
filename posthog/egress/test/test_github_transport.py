import uuid
from functools import partial

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
import fakeredis
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.github.transport import (
    GITHUB_CONDITIONAL_CACHE_MAX_ENTRY_BYTES,
    GITHUB_CONDITIONAL_CACHE_TTL_SECONDS,
    GitHubClient,
    github_request,
)
from posthog.egress.limiter.outbound import OutboundRateLimitAdmission, OutboundRateLimitReservation


def _response(status: int = 200, *, headers: dict[str, str] | None = None, body: bytes = b"{}") -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers or {})
    response._content = body
    prepared = requests.models.PreparedRequest()
    prepared.method = "GET"
    prepared.url = "https://api.github.com/search/code"
    response.request = prepared
    return response


class TestGitHubTransport(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis = fakeredis.FakeRedis()
        self.installation_id = uuid.uuid4().hex
        self.headers = {"Authorization": "Bearer test"}
        self.reservation = OutboundRateLimitReservation(token=None)
        self.reserve = patch(
            "posthog.egress.github.transport.reserve_github_installation_sync",
            return_value=OutboundRateLimitAdmission(granted=True, reservation=self.reservation),
        ).start()
        self.release = patch(
            "posthog.egress.github.transport.release_github_installation_sync", return_value=True
        ).start()
        self.get_client = patch("posthog.egress.github.transport.get_client", return_value=self.redis).start()
        self.addCleanup(patch.stopall)

    @parameterized.expand(
        [
            ("code_search", "https://api.github.com/search/code?q=x", GitHubRateResource.CODE_SEARCH),
            ("core", "https://api.github.com/repos/o/r/pulls/1", GitHubRateResource.CORE),
        ]
    )
    def test_reserve_routes_resource_by_url(self, _name: str, url: str, expected: GitHubRateResource) -> None:
        # The gate must charge each URL to the meter GitHub bills it against — the whole point of the
        # per-resource split. A regression here reverts /search/code to the core envelope.
        GitHubClient()._reserve("42", MagicMock(), "test", url)
        assert self.reserve.call_args.kwargs["resource"] == expected

    def test_identity_blind_call_never_touches_the_limiter(self) -> None:
        # A None installation_id (public token / raw PAT) records volume only and must skip the gate,
        # or unrelated tokens would share and clobber one phantom budget.
        with (
            patch("requests.request", return_value=_response()),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request("GET", "https://api.github.com/search/code?q=x", source="test", installation_id=None)
        self.reserve.assert_not_called()

    def test_get_with_etag_stores_the_response_with_a_ttl(self) -> None:
        with (
            patch("requests.request", return_value=_response(headers={"ETag": '"v1"'}, body=b"cached")),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
            )

        keys = list(self.redis.scan_iter("github_egress:conditional_response:*"))
        assert len(keys) == 1
        assert 0 < self.redis.ttl(keys[0]) <= GITHUB_CONDITIONAL_CACHE_TTL_SECONDS

    def test_matching_304_returns_the_cached_body_and_releases_the_budget(self) -> None:
        statuses: list[int] = []
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"'}, body=b'{"items":[1]}'),
                _response(status=304, headers={"ETag": '"v1"'}, body=b""),
            ]
        )

        with (
            patch("requests.request", sender),
            patch(
                "posthog.egress.github.transport.record_github_api_response",
                side_effect=lambda response, **_kwargs: statuses.append(response.status_code),
            ),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
            )
            response = github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
            )

        assert sender.call_args_list[1].kwargs["headers"]["If-None-Match"] == '"v1"'
        assert response.status_code == 200
        assert response.json() == {"items": [1]}
        assert statuses == [200, 304]
        self.release.assert_called_once_with(self.reservation)

    def test_304_refetches_when_the_entry_is_lost_mid_flight(self) -> None:
        # An entry evicted between the probe and the response would otherwise return an empty 200.
        responses = [
            _response(headers={"ETag": '"v1"'}, body=b'{"items":[1]}'),
            _response(status=304, headers={"ETag": '"v1"'}, body=b""),
            _response(headers={"ETag": '"v2"'}, body=b'{"items":[2]}'),
        ]

        def _send(*_args: object, **_kwargs: object) -> requests.Response:
            response = responses[sender.call_count - 1]
            if response.status_code == 304:
                self.redis.flushall()
            return response

        sender = MagicMock(side_effect=_send)
        request = partial(
            github_request,
            "GET",
            "https://api.github.com/repos/o/r/branches",
            source="test",
            headers=self.headers,
            installation_id=self.installation_id,
        )

        with (
            patch("requests.request", sender),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            request()
            response = request()

        assert sender.call_count == 3
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]
        assert response.status_code == 200
        assert response.json() == {"items": [2]}

    @parameterized.expand(
        [
            ("missing_etag", {}, b"cached"),
            ("oversized_body", {"ETag": '"v1"'}, b"x" * GITHUB_CONDITIONAL_CACHE_MAX_ENTRY_BYTES),
        ]
    )
    def test_uncacheable_get_stores_nothing(self, _name: str, headers: dict[str, str], body: bytes) -> None:
        with (
            patch("requests.request", return_value=_response(headers=headers, body=body)),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
            )

        assert list(self.redis.scan_iter("github_egress:conditional_response:*")) == []

    def test_non_get_request_does_not_use_the_conditional_cache(self) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}, body=b"cached"))
        with (
            patch("requests.request", sender),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request(
                "POST",
                "https://api.github.com/repos/o/r/issues",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
            )

        assert "If-None-Match" not in sender.call_args.kwargs["headers"]
        assert list(self.redis.scan_iter("github_egress:conditional_response:*")) == []
        self.release.assert_not_called()

    @parameterized.expand(
        [
            ("different_installation", "other-installation", {"page": 1}),
            ("different_query", None, {"page": 2}),
        ]
    )
    def test_cache_key_is_scoped_to_installation_and_full_url(
        self, _name: str, second_installation: str | None, second_params: dict[str, int]
    ) -> None:
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"'}, body=b"cached"),
                _response(body=b"fresh"),
            ]
        )
        with (
            patch("requests.request", sender),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=self.installation_id,
                params={"page": 1},
            )
            github_request(
                "GET",
                "https://api.github.com/repos/o/r/branches",
                source="test",
                headers=self.headers,
                installation_id=second_installation or self.installation_id,
                params=second_params,
            )

        assert "If-None-Match" not in sender.call_args_list[1].kwargs["headers"]
