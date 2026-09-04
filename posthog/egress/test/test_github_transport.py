from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.github.transport import GITHUB_API_VERSION, GitHubClient, github_request

_JSON = "application/vnd.github+json"
_DIFF = "application/vnd.github.diff"


# GitHub sends this Vary on every response; a storability rule that rejects it silently disables the cache.
_GITHUB_VARY = "Accept, Authorization, Cookie, X-GitHub-OTP,Accept-Encoding, Accept, X-Requested-With"


def _response(status: int = 200, *, headers: dict[str, str] | None = None, body: bytes = b"{}") -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({"Vary": _GITHUB_VARY, **(headers or {})})
    response._content = body
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
    def test_gate_routes_resource_by_url(self, _name: str, url: str, expected: GitHubRateResource) -> None:
        # The gate must charge each URL to the meter GitHub bills it against — the whole point of the
        # per-resource split. A regression here reverts /search/code to the core envelope.
        client = GitHubClient()
        with (
            patch("posthog.egress.github.transport.peek_github_installation_sync", return_value=True) as peek,
            patch("posthog.egress.github.transport.charge_github_installation_sync") as charge,
        ):
            client._consume("42", MagicMock(), "test", url)
            client._settle(_response(), scope="42", url=url)
        assert peek.call_args.kwargs["resource"] == expected
        assert charge.call_args.kwargs["resource"] == expected

    def test_identity_blind_call_never_touches_the_limiter(self) -> None:
        # A None installation_id (public token / raw PAT) records volume only and must skip the gate,
        # or unrelated tokens would share and clobber one phantom budget.
        with (
            patch("posthog.egress.github.transport.peek_github_installation_sync") as peek,
            patch("posthog.egress.github.transport.charge_github_installation_sync") as charge,
            patch("requests.request", return_value=_response()),
            patch("posthog.egress.github.transport.record_github_api_response"),
        ):
            github_request("GET", "https://api.github.com/search/code?q=x", source="test", installation_id=None)
        peek.assert_not_called()
        charge.assert_not_called()


class TestGitHubConditionalRequests(SimpleTestCase):
    url = "https://api.github.com/repos/o/r/branches"

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        patch("posthog.egress.github.transport.peek_github_installation_sync", return_value=True).start()
        self.charge = patch("posthog.egress.github.transport.charge_github_installation_sync").start()
        patch("posthog.egress.github.transport.record_github_api_response").start()
        self.addCleanup(patch.stopall)

    def _get(self, sender: MagicMock, **kwargs) -> requests.Response:
        with patch("requests.request", sender):
            return github_request(
                kwargs.pop("method", "GET"),
                self.url,
                source="test",
                headers={"Authorization": "Bearer t", **(kwargs.pop("headers", None) or {})},
                installation_id="42",
                cache_identity=kwargs.pop("cache_identity", "installation:42"),
                **kwargs,
            )

    def test_unchanged_resource_is_revalidated_and_replayed_as_200(self) -> None:
        statuses: list[int] = []
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": 'W/"v1"', "Content-Type": "application/json"}, body=b'{"items":[1]}'),
                _response(status=304, headers={"ETag": 'W/"v1"'}),
            ]
        )
        with patch(
            "posthog.egress.github.transport.record_github_api_response",
            side_effect=lambda response, **_: statuses.append(response.status_code),
        ):
            self._get(sender)
            replayed = self._get(sender)

        assert sender.call_args.kwargs["headers"]["If-None-Match"] == 'W/"v1"'
        assert replayed.status_code == 200
        assert replayed.json() == {"items": [1]}
        # The recorder must still see the real 304, or the rate-limit telemetry starts lying.
        assert statuses == [200, 304]
        assert self.charge.call_count == 1

    def test_replay_carries_the_stored_content_type(self) -> None:
        # A 304 need not repeat Content-Type; without it .text goes through charset sniffing.
        sender = MagicMock(
            side_effect=[
                _response(
                    headers={"ETag": '"v1"', "Content-Type": "text/plain; charset=utf-8", "Link": "<next>; rel=next"},
                    body="diff --git a/é b/é".encode(),
                ),
                _response(status=304, headers={"ETag": '"v1"'}),
            ]
        )
        self._get(sender)
        replayed = self._get(sender)

        assert replayed.encoding == "utf-8"
        assert replayed.text == "diff --git a/é b/é"
        assert replayed.headers["Link"] == "<next>; rel=next"

    def test_replay_carries_the_live_rate_limit_headers(self) -> None:
        # remember_observed_core_limit reads these off the replay; a cache-only installation would stop
        # re-learning its tier.
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"', "Content-Type": "application/json"}),
                _response(
                    status=304,
                    headers={
                        "ETag": '"v1"',
                        "X-RateLimit-Resource": "core",
                        "X-RateLimit-Limit": "5000",
                        "X-RateLimit-Remaining": "4998",
                    },
                ),
            ]
        )
        self._get(sender)
        replayed = self._get(sender)

        assert replayed.headers["X-RateLimit-Resource"] == "core"
        assert replayed.headers["X-RateLimit-Limit"] == "5000"
        assert replayed.headers["X-RateLimit-Remaining"] == "4998"
        assert "Content-Length" not in replayed.headers

    @parameterized.expand(
        [
            ("different_identity", {"cache_identity": "installation:99"}),
            ("different_query", {"params": {"page": 2}}),
            ("different_accept", {"headers": {"Accept": _DIFF}}),
            ("different_api_version", {"headers": {"X-GitHub-Api-Version": "2099-01-01"}}),
        ]
    )
    def test_key_separates(self, _name: str, second: dict) -> None:
        # /compare/{basehead} is read as diff and as JSON under one installation; an Accept-blind key
        # makes them overwrite each other.
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"', "Content-Type": "application/json"}),
                _response(headers={"ETag": '"v2"', "Content-Type": "application/json"}),
            ]
        )
        first = {"headers": {"Accept": _JSON}, "params": {"page": 1}}
        self._get(sender, **first)
        self._get(sender, **{**first, **second})

        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    @parameterized.expand(
        [
            ("no_etag", {"Content-Type": "application/json"}, b"{}", {}),
            ("no_store", {"ETag": '"v1"', "Cache-Control": "private, no-store"}, b"{}", {}),
            ("vary_star", {"ETag": '"v1"', "Vary": "*"}, b"{}", {}),
            ("oversized", {"ETag": '"v1"'}, b"x" * 9, {"GITHUB_EGRESS_CONDITIONAL_CACHE_MAX_BODY_BYTES": 8}),
            ("zero_ttl", {"ETag": '"v1"'}, b"{}", {"GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS": 0}),
        ]
    )
    def test_unstorable_response_is_not_reused(self, _name: str, headers: dict, body: bytes, overrides: dict) -> None:
        sender = MagicMock(return_value=_response(headers=headers, body=body))
        with self.settings(**overrides):
            self._get(sender)
            self._get(sender)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    def test_caller_supplied_validator_is_left_alone(self) -> None:
        # The caller owns the exchange; their 304 is not our cache hit.
        sender = MagicMock(return_value=_response(status=304, headers={"ETag": '"theirs"'}))
        response = self._get(sender, headers={"If-None-Match": '"theirs"'})

        assert sender.call_args.kwargs["headers"]["If-None-Match"] == '"theirs"'
        assert response.status_code == 304

    @parameterized.expand(
        [
            ("no_identity", {"cache_identity": None}),
            ("streamed", {"stream": True}),
            ("post", {"method": "POST"}),
        ]
    )
    def test_opted_out_request_is_never_cached(self, _name: str, kwargs: dict) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}))
        self._get(sender, **kwargs)
        self._get(sender, **kwargs)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    def test_the_transport_default_accept_keys_the_same_as_an_explicit_one(self) -> None:
        # The key reads merged headers, so an omitted Accept must key the same as the default the
        # transport sends.
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"', "Content-Type": "application/json"}),
                _response(status=304, headers={"ETag": '"v1"'}),
            ]
        )
        self._get(sender)
        self._get(sender, headers={"Accept": _JSON, "X-GitHub-Api-Version": GITHUB_API_VERSION})
        assert sender.call_args.kwargs["headers"]["If-None-Match"] == '"v1"'
