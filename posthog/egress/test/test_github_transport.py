from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.github.transport import GITHUB_API_VERSION, GitHubClient, github_request

_JSON = "application/vnd.github+json"
_DIFF = "application/vnd.github.diff"


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


class TestGitHubConditionalRequests(SimpleTestCase):
    """The TEST cache backend is process-local LocMem, so each case clears it."""

    url = "https://api.github.com/repos/o/r/branches"

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.consume = patch(
            "posthog.egress.github.transport.consume_github_installation_sync", return_value=True
        ).start()
        patch("posthog.egress.github.transport.record_github_api_response").start()
        self.addCleanup(patch.stopall)

    def _get(self, sender: MagicMock, **kwargs) -> requests.Response:
        with patch("requests.request", sender):
            return github_request(
                "GET",
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

        # The weak validator goes back verbatim; If-None-Match uses weak comparison.
        assert sender.call_args.kwargs["headers"]["If-None-Match"] == 'W/"v1"'
        assert replayed.status_code == 200
        assert replayed.json() == {"items": [1]}
        # The recorder must still see the real 304, or the rate-limit telemetry starts lying.
        assert statuses == [200, 304]
        # A 304 is still gated: it is a real request, and only GitHub declines to charge it.
        assert self.consume.call_count == 2

    def test_replay_carries_the_stored_content_type(self) -> None:
        # A 304 need not repeat Content-Type. Replaying its headers would leave encoding unset and send
        # .text through charset sniffing, and the diff path reads .text.
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

    @parameterized.expand(
        [
            ("different_identity", {"cache_identity": "installation:99"}),
            ("different_query", {"params": {"page": 2}}),
            ("different_accept", {"headers": {"Accept": _DIFF}}),
        ]
    )
    def test_key_separates(self, _name: str, second: dict) -> None:
        # /repos/{o}/{r}/compare/{basehead} is fetched as a diff and as JSON under one installation, so
        # an Accept-blind key makes those two callers overwrite each other and neither ever hits.
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
            ("no_etag", {"Content-Type": "application/json"}),
            ("no_store", {"ETag": '"v1"', "Cache-Control": "private, no-store"}),
            ("unaccounted_vary", {"ETag": '"v1"', "Vary": "Accept, X-Github-Otp"}),
            ("vary_star", {"ETag": '"v1"', "Vary": "*"}),
        ]
    )
    def test_unstorable_response_is_not_reused(self, _name: str, headers: dict) -> None:
        sender = MagicMock(return_value=_response(headers=headers))
        self._get(sender)
        self._get(sender)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    @override_settings(GITHUB_EGRESS_CONDITIONAL_CACHE_MAX_BODY_BYTES=8)
    def test_oversized_body_is_not_stored(self) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}, body=b"x" * 9))
        self._get(sender)
        self._get(sender)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    @override_settings(GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS=0)
    def test_zero_ttl_disables_the_cache(self) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}))
        self._get(sender)
        self._get(sender)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    def test_caller_supplied_validator_is_left_alone(self) -> None:
        # The caller owns the exchange: we must not overwrite their validator, and their 304 is theirs
        # to read rather than ours to mistake for a cache hit.
        sender = MagicMock(return_value=_response(status=304, headers={"ETag": '"theirs"'}))
        response = self._get(sender, headers={"If-None-Match": '"theirs"'})

        assert sender.call_args.kwargs["headers"]["If-None-Match"] == '"theirs"'
        assert response.status_code == 304

    @parameterized.expand([("no_identity", {"cache_identity": None}), ("streamed", {"stream": True})])
    def test_opted_out_request_is_never_cached(self, _name: str, kwargs: dict) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}))
        self._get(sender, **kwargs)
        self._get(sender, **kwargs)
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    def test_non_get_is_never_cached(self) -> None:
        sender = MagicMock(return_value=_response(headers={"ETag": '"v1"'}))
        with patch("requests.request", sender):
            for _ in range(2):
                github_request(
                    "POST",
                    self.url,
                    source="test",
                    headers={"Authorization": "Bearer t"},
                    installation_id="42",
                    cache_identity="installation:42",
                )
        assert "If-None-Match" not in sender.call_args.kwargs["headers"]

    def test_the_transport_default_accept_keys_the_same_as_an_explicit_one(self) -> None:
        # The key reads the merged headers, so omitting Accept must not key on the absence of a header
        # the transport is in fact sending.
        sender = MagicMock(
            side_effect=[
                _response(headers={"ETag": '"v1"', "Content-Type": "application/json"}),
                _response(status=304, headers={"ETag": '"v1"'}),
            ]
        )
        self._get(sender)
        self._get(sender, headers={"Accept": _JSON, "X-GitHub-Api-Version": GITHUB_API_VERSION})
        assert sender.call_args.kwargs["headers"]["If-None-Match"] == '"v1"'
