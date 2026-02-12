import base64

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import (
    padding as asym_padding,
    rsa,
)
from parameterized import parameterized

from posthog.domain_connect import (
    DOMAIN_CONNECT_PROVIDERS,
    build_sync_apply_url,
    discover_domain_connect,
    extract_root_domain_and_host,
    get_available_providers,
    get_service_id_for_region,
    sign_query_string,
)


class TestExtractRootDomainAndHost(BaseTest):
    @parameterized.expand(
        [
            ("simple subdomain", "ph.example.com", ("example.com", "ph")),
            ("bare domain", "example.com", ("example.com", "")),
            ("deep subdomain", "a.b.c.example.com", ("example.com", "a.b.c")),
            ("co.uk domain", "ph.example.co.uk", ("example.co.uk", "ph")),
            ("deep co.uk", "track.sub.example.co.uk", ("example.co.uk", "track.sub")),
            ("bare co.uk", "example.co.uk", ("example.co.uk", "")),
            ("com.au domain", "app.example.com.au", ("example.com.au", "app")),
            ("trailing dot", "ph.example.com.", ("example.com", "ph")),
            ("single label", "localhost", ("localhost", "")),
        ]
    )
    def test_extraction(self, _name: str, fqdn: str, expected: tuple[str, str]) -> None:
        self.assertEqual(extract_root_domain_and_host(fqdn), expected)


class TestGetServiceIdForRegion(BaseTest):
    @parameterized.expand(
        [
            ("US deployment", "US", "email-verification-us"),
            ("EU deployment", "EU", "email-verification-eu"),
            ("eu lowercase", "eu", "email-verification-eu"),
            ("None deployment", None, "email-verification-us"),
            ("DEV deployment", "DEV", "email-verification-us"),
        ]
    )
    def test_region_mapping(self, _name: str, deployment: str | None, expected: str) -> None:
        with self.settings(CLOUD_DEPLOYMENT=deployment):
            self.assertEqual(get_service_id_for_region("email-verification"), expected)


class TestBuildSyncApplyUrl(BaseTest):
    def test_basic_url(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"host": "ph", "target": "abc123.proxy.posthog.com"},
        )

        self.assertIn("/v2/domainTemplates/providers/posthog.com/services/reverse-proxy-us/apply?", url)
        self.assertIn("domain=example.com", url)
        self.assertIn("host=ph", url)
        self.assertIn("target=abc123.proxy.posthog.com", url)

    def test_url_with_redirect(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"host": "ph", "target": "abc.proxy.posthog.com"},
            redirect_uri="https://us.posthog.com/settings?domain_connect=proxy",
        )

        self.assertIn("redirect_uri=", url)

    def test_url_with_signing(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"host": "ph", "target": "abc.proxy.posthog.com"},
            private_key=private_key,
            key_id="_dck1",
        )

        self.assertIn("sig=", url)
        self.assertIn("key=_dck1", url)

    def test_url_without_signing_key_has_no_sig(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"host": "ph", "target": "abc.proxy.posthog.com"},
        )

        self.assertNotIn("sig=", url)
        self.assertNotIn("key=", url)


class TestSignQueryString(BaseTest):
    def test_sign_and_verify(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        query = "domain=example.com&host=ph&target=abc.proxy.posthog.com"
        signature_b64 = sign_query_string(query, private_key)

        signature_bytes = base64.urlsafe_b64decode(signature_b64)
        # Should not raise
        public_key.verify(
            signature_bytes,
            query.encode("utf-8"),
            asym_padding.PKCS1v15(),
            crypto_hashes.SHA256(),
        )


class TestDiscoverDomainConnect(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @patch("posthog.domain_connect._fetch_provider_settings")
    @patch("posthog.domain_connect._lookup_domain_connect_endpoint")
    def test_supported_provider(self, mock_lookup: MagicMock, mock_settings: MagicMock) -> None:
        mock_lookup.return_value = "api.cloudflare.com/client/v4/dns/domainconnect"
        mock_settings.return_value = {"urlSyncUX": "https://dash.cloudflare.com/domainconnect"}

        with patch.dict(DOMAIN_CONNECT_PROVIDERS, {"api.cloudflare.com/client/v4/dns/domainconnect": "Cloudflare"}):
            result = discover_domain_connect("example.com")

        self.assertIsNotNone(result)
        self.assertEqual(result["provider_name"], "Cloudflare")
        self.assertEqual(result["url_sync_ux"], "https://dash.cloudflare.com/domainconnect")

    @patch("posthog.domain_connect._lookup_domain_connect_endpoint")
    def test_unsupported_provider(self, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = "unknown.provider.example"

        result = discover_domain_connect("example.com")

        self.assertIsNone(result)

    @patch("posthog.domain_connect._lookup_domain_connect_endpoint")
    def test_no_txt_record(self, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = None

        result = discover_domain_connect("example.com")

        self.assertIsNone(result)

    @patch("posthog.domain_connect._fetch_provider_settings")
    @patch("posthog.domain_connect._lookup_domain_connect_endpoint")
    def test_provider_settings_unavailable(self, mock_lookup: MagicMock, mock_settings: MagicMock) -> None:
        mock_lookup.return_value = "api.cloudflare.com/client/v4/dns/domainconnect"
        mock_settings.return_value = None

        with patch.dict(DOMAIN_CONNECT_PROVIDERS, {"api.cloudflare.com/client/v4/dns/domainconnect": "Cloudflare"}):
            result = discover_domain_connect("example.com")

        self.assertIsNone(result)


class TestGetAvailableProviders(BaseTest):
    def test_returns_all_providers(self) -> None:
        with patch.dict(
            DOMAIN_CONNECT_PROVIDERS,
            {"api.cloudflare.com/client/v4/dns/domainconnect": "Cloudflare", "dnstemplate.godaddy.com": "GoDaddy"},
            clear=True,
        ):
            providers = get_available_providers()

        self.assertEqual(len(providers), 2)
        names = {p["name"] for p in providers}
        self.assertIn("Cloudflare", names)
        self.assertIn("GoDaddy", names)

    def test_empty_when_no_providers(self) -> None:
        with patch.dict(DOMAIN_CONNECT_PROVIDERS, {}, clear=True):
            providers = get_available_providers()

        self.assertEqual(providers, [])
