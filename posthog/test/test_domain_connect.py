import re
import json
import base64
from pathlib import Path

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
    DomainConnectSigningKeyMissing,
    build_sync_apply_url,
    discover_domain_connect,
    extract_root_domain_and_host,
    generate_apply_url,
    get_available_providers,
    get_service_id_for_region,
    resolve_email_context,
    resolve_proxy_context,
    sign_query_string,
)

TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "components" / "DomainConnect" / "templates"
)


def _load_template(filename: str) -> dict:
    return json.loads((TEMPLATE_DIR / filename).read_text())


def _extract_template_variables(template: dict) -> set[str]:
    """Extract all %variable% placeholders from a template's records."""
    variables: set[str] = set()
    pattern = re.compile(r"%(\w+)%")
    for record in template.get("records", []):
        for value in record.values():
            if isinstance(value, str):
                variables.update(pattern.findall(value))
    return variables


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
    def test_extraction(self, name: str, full_domain: str, expected: tuple[str, str]) -> None:
        self.assertEqual(
            extract_root_domain_and_host(full_domain),
            expected,
            f"Failed for case {name} for domain {full_domain}",
        )


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
            variables={"target": "abc123.proxy.posthog.com"},
            host="ph",
        )

        self.assertIn("/v2/domainTemplates/providers/posthog.com/services/reverse-proxy-us/apply?", url)
        self.assertIn("domain=example.com", url)
        self.assertIn("host=ph", url)
        self.assertIn("target=abc123.proxy.posthog.com", url)

    def test_url_without_host(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="email-verification-us",
            domain="example.com",
            variables={"verifyToken": "abc123"},
        )

        self.assertNotIn("host=", url)
        self.assertIn("domain=example.com", url)
        self.assertIn("verifyToken=abc123", url)

    def test_url_with_redirect(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"target": "abc.proxy.posthog.com"},
            host="ph",
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
            variables={"target": "abc.proxy.posthog.com"},
            host="ph",
            private_key=private_key,
            key_id="_dcpubkeyv1",
        )

        self.assertIn("sig=", url)
        self.assertIn("key=_dcpubkeyv1", url)

    def test_url_without_signing_key_has_no_sig(self) -> None:
        url = build_sync_apply_url(
            url_sync_ux="https://dns.provider.example/sync",
            provider_id="posthog.com",
            service_id="reverse-proxy-us",
            domain="example.com",
            variables={"target": "abc.proxy.posthog.com"},
            host="ph",
        )

        self.assertNotIn("sig=", url)
        self.assertNotIn("key=", url)


class TestSignQueryString(BaseTest):
    def test_sign_and_verify(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        query = "domain=example.com&host=ph&target=abc.proxy.posthog.com"
        signature_b64 = sign_query_string(query, private_key)

        signature_bytes = base64.b64decode(signature_b64)
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

        if result:
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


class TestGenerateApplyUrl(BaseTest):
    def test_rejects_unknown_provider_endpoint(self) -> None:
        with self.assertRaises(ValueError, msg="Unsupported provider endpoint"):
            generate_apply_url(
                domain="example.com",
                service_id="reverse-proxy-us",
                variables={"target": "abc.proxy.posthog.com"},
                provider_endpoint="evil.internal.service",
            )

    @patch("posthog.domain_connect._fetch_provider_settings")
    @patch("posthog.domain_connect.get_signing_key")
    def test_allows_known_provider_endpoint(self, mock_key: MagicMock, mock_settings: MagicMock) -> None:
        mock_key.return_value = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        mock_settings.return_value = {"urlSyncUX": "https://dash.cloudflare.com/domainconnect"}

        url = generate_apply_url(
            domain="example.com",
            service_id="reverse-proxy-us",
            variables={"target": "abc.proxy.posthog.com"},
            provider_endpoint="api.cloudflare.com/client/v4/dns/domainconnect",
        )

        self.assertIn("domain=example.com", url)
        self.assertIn("sig=", url)

    @patch("posthog.domain_connect.get_signing_key")
    def test_rejects_signing_required_provider_without_key(self, mock_key: MagicMock) -> None:
        mock_key.return_value = None

        with self.assertRaises(DomainConnectSigningKeyMissing):
            generate_apply_url(
                domain="example.com",
                service_id="reverse-proxy-us",
                variables={"target": "abc.proxy.posthog.com"},
                provider_endpoint="api.cloudflare.com/client/v4/dns/domainconnect",
            )

    @patch("posthog.domain_connect.discover_domain_connect")
    @patch("posthog.domain_connect.get_signing_key")
    def test_rejects_discovered_signing_required_provider_without_key(
        self, mock_key: MagicMock, mock_discover: MagicMock
    ) -> None:
        mock_key.return_value = None
        mock_discover.return_value = {
            "provider_name": "Cloudflare",
            "endpoint": "api.cloudflare.com/client/v4/dns/domainconnect",
            "url_sync_ux": "https://dash.cloudflare.com/domainconnect",
        }

        with self.assertRaises(DomainConnectSigningKeyMissing):
            generate_apply_url(
                domain="example.com",
                service_id="reverse-proxy-us",
                variables={"target": "abc.proxy.posthog.com"},
            )


class TestTemplateResolverAlignment(BaseTest):
    """Ensure backend resolvers produce variables that exactly match the template placeholders."""

    @parameterized.expand(
        [
            ("posthog.com.reverse-proxy-us.json", "US"),
            ("posthog.com.reverse-proxy-eu.json", "EU"),
        ]
    )
    @patch("posthog.models.ProxyRecord")
    def test_proxy_resolver_variables_match_template(
        self, template_file: str, region: str, mock_proxy_cls: MagicMock
    ) -> None:
        template = _load_template(template_file)
        expected_vars = _extract_template_variables(template)

        mock_record = MagicMock()
        mock_record.domain = "ph.example.com"
        mock_record.target_cname = "abc.proxy.posthog.com"
        mock_proxy_cls.objects.get.return_value = mock_record

        with self.settings(CLOUD_DEPLOYMENT=region):
            domain, service_id, host, variables = resolve_proxy_context("test-id", "test-org")

        self.assertEqual(set(variables.keys()), expected_vars)
        self.assertEqual(service_id, template["serviceId"])
        if template.get("hostRequired"):
            self.assertTrue(host, "hostRequired template but resolver returned empty host")

    @parameterized.expand(
        [
            ("posthog.com.email-verification-us.json", "US"),
            ("posthog.com.email-verification-eu.json", "EU"),
        ]
    )
    @patch("posthog.models.integration.EmailIntegration")
    @patch("posthog.models.integration.Integration")
    def test_email_resolver_variables_match_template(
        self, template_file: str, region: str, mock_integration_cls: MagicMock, mock_email_cls: MagicMock
    ) -> None:
        template = _load_template(template_file)
        expected_vars = _extract_template_variables(template)

        mock_instance = MagicMock()
        mock_instance.kind = "email"
        mock_instance.config = {"domain": "example.com", "mail_from_subdomain": "feedback"}
        mock_integration_cls.objects.get.return_value = mock_instance

        mock_email = MagicMock()
        mock_email.verify.return_value = {
            "dnsRecords": [
                {
                    "type": "verification",
                    "recordType": "TXT",
                    "recordHostname": "_amazonses.example.com",
                    "recordValue": "verify-token-123",
                },
                {"type": "dkim", "recordHostname": "aaa._domainkey.example.com"},
                {"type": "dkim", "recordHostname": "bbb._domainkey.example.com"},
                {"type": "dkim", "recordHostname": "ccc._domainkey.example.com"},
            ]
        }
        mock_email_cls.return_value = mock_email

        with self.settings(CLOUD_DEPLOYMENT=region, SES_REGION="us-east-1"):
            domain, service_id, variables = resolve_email_context(1, 1)

        self.assertEqual(set(variables.keys()), expected_vars)
        self.assertEqual(service_id, template["serviceId"])
