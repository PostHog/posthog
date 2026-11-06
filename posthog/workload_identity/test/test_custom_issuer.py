from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.oauth.cimd import CIMDFetchError
from posthog.workload_identity.custom_issuer import (
    CustomIssuerError,
    CustomIssuerMetadata,
    CustomIssuerUnavailable,
    discover_custom_issuer,
    validate_custom_issuer_url,
)

ISSUER = "https://idp.example.com"
FETCH = "posthog.api.oauth.cimd.fetch_client_json_document"


def _discovery(**overrides: Any) -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "jwks_uri": f"{ISSUER}/keys",
        "id_token_signing_alg_values_supported": ["RS256", "ES256"],
        **overrides,
    }


class TestCustomIssuer(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            ("plain_http", "http://idp.example.com"),
            ("userinfo", "https://user:pass@idp.example.com"),
            ("ip_literal", "https://10.0.0.1"),
            ("ipv6_literal", "https://[::1]"),
            ("query", "https://idp.example.com?tenant=x"),
            ("registry_issuer", "https://token.actions.githubusercontent.com"),
        ]
    )
    def test_refuses_an_issuer_url_it_must_not_fetch(self, _name: str, issuer: str) -> None:
        with patch(FETCH) as fetch:
            with self.assertRaises(CustomIssuerError):
                discover_custom_issuer(issuer)

        assert not fetch.called

    @parameterized.expand(
        [
            ("another_issuer", {"issuer": "https://other.example.com"}),
            ("http_jwks_uri", {"jwks_uri": "http://idp.example.com/keys"}),
            ("ip_jwks_uri", {"jwks_uri": "https://169.254.169.254/keys"}),
            ("symmetric_algorithms_only", {"id_token_signing_alg_values_supported": ["HS256", "none"]}),
            ("no_jwks_uri", {"jwks_uri": None}),
        ]
    )
    def test_refuses_a_discovery_document_it_can_not_trust(self, _name: str, overrides: dict[str, Any]) -> None:
        with patch(FETCH, return_value=(_discovery(**overrides), MagicMock())):
            with self.assertRaises(CustomIssuerError) as raised:
                discover_custom_issuer(ISSUER)

        assert not isinstance(raised.exception, CustomIssuerUnavailable)

    def test_keeps_only_the_asymmetric_algorithms_it_reads(self) -> None:
        document = _discovery(id_token_signing_alg_values_supported=["HS256", "RS256"])

        with patch(FETCH, return_value=(document, MagicMock())) as fetch:
            first = discover_custom_issuer(ISSUER)
            second = discover_custom_issuer(ISSUER)

        assert (
            first
            == second
            == CustomIssuerMetadata(issuer=ISSUER, jwks_uri=f"{ISSUER}/keys", signing_algorithms=("RS256",))
        )
        assert fetch.call_count == 1
        assert fetch.call_args.args[0] == f"{ISSUER}/.well-known/openid-configuration"

    def test_a_host_the_ssrf_guard_refuses_is_never_requested(self) -> None:
        verdict = MagicMock(allowed=False, reason="private address", pinned_ips=[])

        with (
            patch("posthog.api.oauth.cimd.validate_url_and_pin_ips", return_value=verdict),
            patch("posthog.api.oauth.cimd.requests.Session") as session,
        ):
            with self.assertRaises(CustomIssuerError):
                discover_custom_issuer(ISSUER)

        assert not session.called

    def test_a_failed_fetch_is_remembered_briefly_instead_of_fetched_on_every_exchange(self) -> None:
        with patch(FETCH, side_effect=CIMDFetchError("could not connect")) as fetch:
            for _ in range(3):
                with self.assertRaises(CustomIssuerUnavailable):
                    discover_custom_issuer(ISSUER)

        assert fetch.call_count == 1

    def test_an_issuer_with_a_path_keeps_its_exact_spelling(self) -> None:
        assert validate_custom_issuer_url("https://example.auth0.com/") == "https://example.auth0.com/"
