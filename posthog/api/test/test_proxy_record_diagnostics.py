import ipaddress
from dataclasses import replace

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

import requests
import dns.resolver
from parameterized import parameterized

from posthog.api import proxy_record_diagnostics as diagnostics
from posthog.models.proxy_record import is_valid_proxy_domain
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    CustomHostname,
    CustomHostnameSSL,
    CustomHostnameSSLStatus,
    CustomHostnameStatus,
)


def _record(domain: str = "e.example.com", target: str = "abc.cf-prod-eu-proxy.europehog.com."):
    """Build a minimal ProxyRecord-like stub. Avoids hitting the DB.

    `target` includes the trailing FQDN dot to match the production data shape:
    `generate_target_cname` produces `{digest}.{CLOUDFLARE_PROXY_BASE_CNAME}` where the
    env var ends with a dot.
    """
    rec = MagicMock()
    rec.id = "00000000-0000-0000-0000-000000000001"
    rec.organization_id = "00000000-0000-0000-0000-000000000002"
    rec.domain = domain
    rec.target_cname = target
    return rec


def _hostname_info(
    ssl_status: CustomHostnameSSLStatus = CustomHostnameSSLStatus.PENDING_VALIDATION,
    http_url: str | None = "http://e.example.com/.well-known/acme-challenge/tok",
    http_body: str | None = "tok.body",
    certificate_authority: str | None = "google",
) -> CustomHostname:
    return CustomHostname(
        id="hostname-id",
        hostname="e.example.com",
        status=CustomHostnameStatus.ACTIVE,
        ssl=CustomHostnameSSL(
            status=ssl_status,
            validation_errors=[],
            http_url=http_url,
            http_body=http_body,
            certificate_authority=certificate_authority,
            validation_records=[],
        ),
    )


def _caa_rdata(tag: bytes, issuer: str):
    """Mimic a dnspython CAA rdata object."""
    rd = MagicMock()
    rd.tag = tag
    rd.value = issuer.encode()
    return rd


class TestCheckCname(TestCase):
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_pass_when_cname_matches(self, ResolverMock):
        cname = MagicMock()
        cname.target.to_text.return_value = "abc.cf-prod-eu-proxy.europehog.com."
        ResolverMock.return_value.resolve.return_value = [cname]

        result = diagnostics._check_cname(_record())

        self.assertEqual(result.status, "passed")
        self.assertIsNone(result.remediation)

    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_fail_when_cname_mismatches(self, ResolverMock):
        cname = MagicMock()
        cname.target.to_text.return_value = "wrong.example.net."
        ResolverMock.return_value.resolve.return_value = [cname]

        result = diagnostics._check_cname(_record())

        self.assertEqual(result.status, "failed")
        self.assertIn("wrong.example.net", result.detail)
        assert result.remediation is not None
        self.assertEqual(result.remediation.records[0].type, "CNAME")

    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_fail_when_cname_missing_nxdomain(self, ResolverMock):
        ResolverMock.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()

        result = diagnostics._check_cname(_record())

        self.assertEqual(result.status, "failed")
        self.assertIn("doesn't have a CNAME", result.detail)


class TestCheckCloudflare(TestCase):
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_pass_when_ssl_active(self, get_mock):
        get_mock.return_value = _hostname_info(ssl_status=CustomHostnameSSLStatus.ACTIVE)
        result, info = diagnostics._check_cloudflare(_record())
        self.assertEqual(result.status, "passed")
        self.assertIsNotNone(info)

    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_warn_when_pending_validation(self, get_mock):
        get_mock.return_value = _hostname_info(ssl_status=CustomHostnameSSLStatus.PENDING_VALIDATION)
        result, info = diagnostics._check_cloudflare(_record())
        self.assertEqual(result.status, "warned")
        self.assertIn("verification is pending", result.detail.lower())

    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_fail_when_hostname_missing(self, get_mock):
        get_mock.return_value = None
        result, info = diagnostics._check_cloudflare(_record())
        self.assertEqual(result.status, "failed")
        assert result.remediation is not None
        self.assertEqual(result.remediation.type, "retry")
        self.assertIsNone(info)

    @parameterized.expand(
        [
            ("blocked", CustomHostnameStatus.BLOCKED, "zone hold"),
            ("pending_blocked", CustomHostnameStatus.PENDING_BLOCKED, "zone hold"),
            ("moved", CustomHostnameStatus.MOVED, "restore"),
            ("pending_migration", CustomHostnameStatus.PENDING_MIGRATION, "restore"),
        ]
    )
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_fail_when_hostname_blocked_despite_active_cert(self, _name, status, remediation_word, get_mock):
        # An active SSL certificate must not let a blocked or moved hostname pass the check.
        info = replace(_hostname_info(ssl_status=CustomHostnameSSLStatus.ACTIVE), status=status)
        get_mock.return_value = info

        result, _ = diagnostics._check_cloudflare(_record())

        self.assertEqual(result.status, "failed")
        assert result.remediation is not None
        self.assertEqual(result.remediation.type, "config")
        self.assertIn(remediation_word, result.remediation.summary)

    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_fail_when_api_errors(self, get_mock):
        get_mock.side_effect = CloudflareAPIError("boom")
        with patch("posthog.api.proxy_record_diagnostics.capture_exception"):
            result, info = diagnostics._check_cloudflare(_record())
        self.assertEqual(result.status, "failed")
        self.assertIn("certificate provider", result.detail.lower())

    @parameterized.expand(
        [
            # ValueError from cloudflare._get_headers() when CLOUDFLARE_API_TOKEN is unset,
            # or from cloudflare._parse_hostname() when Cloudflare returns an unknown enum
            # status value.
            ("value_error", ValueError("CLOUDFLARE_API_TOKEN must be configured")),
            # KeyError from cloudflare._parse_hostname() if the response is missing a
            # previously-guaranteed field like `id`, `hostname`, or `status`.
            ("key_error", KeyError("status")),
        ]
    )
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    def test_warn_when_unexpected_exception_escapes(self, _name, exc, get_mock):
        get_mock.side_effect = exc
        with patch("posthog.api.proxy_record_diagnostics.capture_exception") as cap_mock:
            result, info = diagnostics._check_cloudflare(_record())
        self.assertEqual(result.status, "warned")
        self.assertIsNone(info)
        self.assertIsNone(result.remediation)
        cap_mock.assert_called_once()
        _exc, props = cap_mock.call_args[0]
        self.assertIn("proxy_record_id", props)
        self.assertIn("domain", props)


class TestCheckCaa(TestCase):
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_pass_when_no_caa_records(self, ResolverMock):
        ResolverMock.return_value.resolve.side_effect = dns.resolver.NoAnswer()
        result = diagnostics._check_caa(_record(), _hostname_info(), is_cloudflare=True)
        self.assertEqual(result.status, "passed")
        self.assertIn("unrestricted", result.detail.lower())

    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_pass_when_caa_authorizes_required_issuer(self, ResolverMock):
        ResolverMock.return_value.resolve.return_value = [_caa_rdata(b"issue", "pki.goog")]
        result = diagnostics._check_caa(_record(), _hostname_info(certificate_authority="google"), is_cloudflare=True)
        self.assertEqual(result.status, "passed")
        self.assertIn("pki.goog", result.detail)

    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_fail_when_caa_blocks_required_issuer(self, ResolverMock):
        ResolverMock.return_value.resolve.return_value = [_caa_rdata(b"issue", "digicert.com")]
        result = diagnostics._check_caa(_record(), _hostname_info(certificate_authority="google"), is_cloudflare=True)
        self.assertEqual(result.status, "failed")
        self.assertIn("digicert.com", result.detail)
        self.assertIn("pki.goog", result.detail)
        assert result.remediation is not None
        self.assertEqual(result.remediation.type, "dns")
        self.assertGreater(len(result.remediation.records), 0)

    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_legacy_proxy_requires_letsencrypt_issuer(self, ResolverMock):
        # Legacy proxies have no Cloudflare hostname info; their cert is Let's Encrypt, so a
        # CAA record authorizing only Google must fail against letsencrypt.org (not pki.goog).
        ResolverMock.return_value.resolve.return_value = [_caa_rdata(b"issue", "pki.goog")]
        result = diagnostics._check_caa(_record(), None, is_cloudflare=False)
        self.assertEqual(result.status, "failed")
        self.assertIn("letsencrypt.org", result.detail)


class TestCheckHttpChallenge(TestCase):
    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    def test_pass_when_body_matches(self, get_mock):
        get_mock.return_value = MagicMock(status_code=200, text="tok.body")
        result = diagnostics._check_http_challenge(_record(), _hostname_info())
        self.assertEqual(result.status, "passed")

    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    def test_fail_when_body_mismatch(self, get_mock):
        get_mock.return_value = MagicMock(status_code=200, text="other content")
        result = diagnostics._check_http_challenge(_record(), _hostname_info())
        self.assertEqual(result.status, "failed")
        self.assertIn("wrong content", result.detail.lower())

    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    def test_fail_when_unreachable(self, get_mock):
        get_mock.side_effect = requests.exceptions.ConnectionError("refused")
        result = diagnostics._check_http_challenge(_record(), _hostname_info())
        self.assertEqual(result.status, "failed")
        assert result.remediation is not None
        self.assertEqual(result.remediation.type, "config")

    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    def test_fail_when_non_200(self, get_mock):
        get_mock.return_value = MagicMock(status_code=404, text="")
        result = diagnostics._check_http_challenge(_record(), _hostname_info())
        self.assertEqual(result.status, "failed")
        self.assertIn("404", result.detail)


class TestCheckLiveEvent(TestCase):
    @parameterized.expand(
        [
            ("ssl_error", requests.exceptions.SSLError("bad cert"), "failed", "tls"),
            ("conn_error", requests.exceptions.ConnectionError("refused"), "failed", "connect"),
        ]
    )
    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_request_exceptions(self, _name, exc, expected_status, expected_substr, post_mock):
        post_mock.side_effect = exc
        result = diagnostics._check_live_event(_record())
        self.assertEqual(result.status, expected_status)
        self.assertIn(expected_substr, result.detail.lower())

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_5xx_is_fail(self, post_mock):
        post_mock.return_value = MagicMock(status_code=502)
        result = diagnostics._check_live_event(_record())
        self.assertEqual(result.status, "failed")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_4xx_is_warn(self, post_mock):
        post_mock.return_value = MagicMock(status_code=403)
        result = diagnostics._check_live_event(_record())
        self.assertEqual(result.status, "warned")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_2xx_is_pass(self, post_mock):
        post_mock.return_value = MagicMock(status_code=200)
        result = diagnostics._check_live_event(_record())
        self.assertEqual(result.status, "passed")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_403_with_cloudflare_1014_fails_with_authorization_message(self, post_mock):
        # A 403 with Cloudflare error 1014 must fail the check with the authorization message.
        post_mock.return_value = MagicMock(status_code=403, text="<h1>Error 1014</h1>")
        result = diagnostics._check_live_event(_record())
        self.assertEqual(result.status, "failed")
        self.assertIn("1014", result.detail)

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_ssrf_block_fails_the_check_instead_of_escaping(self, post_mock):
        # SSRFBlockedError is not a RequestException, so without its own handler it would
        # escape _check_live_event and surface as a 500 from the diagnose endpoint. A domain
        # that resolves somewhere internal has to read as a failed check.
        post_mock.side_effect = SSRFBlockedError("Private IP address not allowed")

        result = diagnostics._check_live_event(_record())

        self.assertEqual(result.status, "failed")
        self.assertIn("public address", result.detail)

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    def test_probe_targets_the_domain_as_the_authority(self, post_mock):
        post_mock.return_value = MagicMock(status_code=200)

        diagnostics._check_live_event(_record())

        self.assertEqual(post_mock.call_args[0][1], "https://e.example.com/i/v0/e/")


PUBLIC_IP = ipaddress.ip_address("203.0.113.10")


@patch(
    "posthog.api.proxy_record_diagnostics.validate_url_and_pin_ips",
    return_value=PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={PUBLIC_IP}),
)
class TestCheckCertExpiry(TestCase):
    @parameterized.expand(
        [
            ("cloudflare_path", True, "retry"),
            ("legacy_path", False, "config"),
        ]
    )
    @patch("posthog.api.proxy_record_diagnostics.ssl_module.create_default_context")
    @patch("posthog.api.proxy_record_diagnostics.socket.create_connection")
    def test_expiring_cert_remediation_depends_on_path(
        self, _name, is_cloudflare, expected_type, _create_conn_mock, ctx_mock, _validate_mock
    ):
        # An expiring cert triggers the failed branch; the remediation differs by path — a
        # Cloudflare proxy can safely re-provision (retry), a legacy proxy must not (config),
        # since retry would migrate it onto Cloudflare and break a working setup.
        wrapped = ctx_mock.return_value.wrap_socket.return_value.__enter__.return_value
        wrapped.getpeercert.return_value = {"notAfter": "Jan  1 00:00:00 2000 GMT"}

        result = diagnostics._check_cert_expiry(_record(), is_cloudflare=is_cloudflare)

        self.assertEqual(result.status, "failed")
        assert result.remediation is not None
        self.assertEqual(result.remediation.type, expected_type)

    @patch("posthog.api.proxy_record_diagnostics.ssl_module.create_default_context")
    @patch("posthog.api.proxy_record_diagnostics.socket.create_connection")
    def test_connects_to_the_validated_address_with_hostname_kept_for_sni(
        self, create_conn_mock, ctx_mock, _validate_mock
    ):
        # The detail strings name the exception class, so an unpinned connection would report
        # whether a port is open on whatever address the name resolves to at connect time.
        # Connecting to the validated address closes that, and SNI has to stay on the hostname
        # or certificate verification would check the literal address instead.
        wrapped = ctx_mock.return_value.wrap_socket.return_value.__enter__.return_value
        wrapped.getpeercert.return_value = {"notAfter": "Jan  1 00:00:00 2100 GMT"}

        diagnostics._check_cert_expiry(_record(), is_cloudflare=True)

        self.assertEqual(create_conn_mock.call_args[0][0], (str(PUBLIC_IP), 443))
        self.assertEqual(ctx_mock.return_value.wrap_socket.call_args.kwargs["server_hostname"], "e.example.com")

    @patch("posthog.api.proxy_record_diagnostics.socket.create_connection")
    def test_warns_without_connecting_when_the_host_is_not_public(self, create_conn_mock, validate_mock):
        validate_mock.return_value = PinnedUrlVerdict(
            allowed=False, reason="Private IP address not allowed", pinned_ips=set()
        )

        result = diagnostics._check_cert_expiry(_record(), is_cloudflare=True)

        create_conn_mock.assert_not_called()
        self.assertEqual(result.status, "warned")


class TestIsValidProxyDomain(TestCase):
    @parameterized.expand(
        [
            ("plain", "e.example.com"),
            ("deep_subdomain", "a.b.c.example.com"),
            ("hyphenated", "other-diagnose.example.com"),
            ("multi_part_tld", "ph.example.co.uk"),
            ("digits_in_label", "proxy0.example.com"),
            ("mixed_case", "Test.Example.COM"),
        ]
    )
    def test_accepts_real_domain_shapes(self, _name, domain):
        self.assertTrue(is_valid_proxy_domain(domain))

    @parameterized.expand(
        [
            # A legal DNS query name that `requests` reads as the authority
            # `169.254.169.254:80` with the rest demoted to the path.
            ("authority_smuggled_into_label", "169.254.169.254:80/pad.attacker.example"),
            ("port", "e.example.com:8080"),
            ("path", "e.example.com/i/v0/e/"),
            ("scheme", "https://e.example.com"),
            ("userinfo", "e.example.com@attacker.example"),
            ("backslash", "e.example.com\\@attacker.example"),
            ("whitespace", "e.example.com "),
            ("ipv4_literal", "169.254.169.254"),
            ("ipv6_literal", "[::1]"),
            ("single_label", "localhost"),
            ("trailing_dot", "e.example.com."),
            ("empty_label", "e..example.com"),
            ("leading_hyphen_label", "-e.example.com"),
            ("underscore", "_dmarc.example.com"),
            ("wildcard", "*.example.com"),
            ("empty", ""),
            ("oversized_label", f"{'a' * 64}.example.com"),
            ("oversized_total", ".".join(["a" * 63] * 4) + ".com"),
        ]
    )
    def test_rejects_non_hostname_shapes(self, _name, domain):
        self.assertFalse(is_valid_proxy_domain(domain))


CF_TARGET = "abc.cf-prod-eu-proxy.europehog.com."
LEGACY_TARGET = "abc.proxy-us.posthog.com."


@override_settings(CLOUDFLARE_PROXY_BASE_CNAME="cf-prod-eu-proxy.europehog.com")
class TestDiagnoseOrchestrator(TestCase):
    """End-to-end orchestrator with all external deps mocked.

    Path is detected from `target_cname` vs `CLOUDFLARE_PROXY_BASE_CNAME` (overridden above):
    `CF_TARGET` reads as a Cloudflare proxy, `LEGACY_TARGET` as a legacy one.
    """

    @parameterized.expand([("cloudflare_path", CF_TARGET), ("legacy_path", LEGACY_TARGET)])
    @patch("posthog.api.proxy_record_diagnostics._check_cert_expiry")
    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_live_pass_short_circuits_to_healthy(self, _name, target, ResolverMock, get_mock, post_mock, cert_mock):
        # A working endpoint means the cert is live and deployed, so no provider API is
        # consulted — on either path. This is the regression that made a healthy legacy
        # proxy report as broken because its Cloudflare lookup came back empty.
        cname = MagicMock()
        cname.target.to_text.return_value = target
        ResolverMock.return_value.resolve.return_value = [cname]
        post_mock.return_value = MagicMock(status_code=200)
        cert_mock.return_value = diagnostics.CheckResult(
            id="cert_expiry", name="Certificate expiry", status="passed", detail="ok"
        )

        report = diagnostics.diagnose(_record(target=target))

        self.assertEqual(report.summary.status, "healthy")
        self.assertEqual([c.id for c in report.checks], ["cname", "live_event", "cert_expiry"])
        get_mock.assert_not_called()

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_cname_failure_skips_live_probe(self, ResolverMock, get_mock, post_mock):
        # SSRF guard: when DNS doesn't confirm the domain points at our managed proxy target,
        # the live probe must not fire an outbound request to the org-controlled hostname.
        cname = MagicMock()
        cname.target.to_text.return_value = "somewhere-else.example.net."

        def resolve_side_effect(name, rdtype):
            if rdtype == "CNAME":
                return [cname]
            raise dns.resolver.NoAnswer()

        ResolverMock.return_value.resolve.side_effect = resolve_side_effect
        get_mock.return_value = None

        report = diagnostics.diagnose(_record(target=CF_TARGET))

        post_mock.assert_not_called()
        live_check = next(c for c in report.checks if c.id == "live_event")
        self.assertEqual(live_check.status, "skipped")
        self.assertEqual(report.summary.primary_issue, "cname")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_legacy_not_serving_skips_cloudflare_and_offers_no_retry(self, ResolverMock, get_mock, post_mock):
        # A broken legacy proxy must skip the Cloudflare check (not fail it), never call the
        # Cloudflare API, and never suggest retry — retry would migrate it onto Cloudflare.
        cname = MagicMock()
        cname.target.to_text.return_value = LEGACY_TARGET

        def resolve_side_effect(name, rdtype):
            if rdtype == "CNAME":
                return [cname]
            raise dns.resolver.NoAnswer()

        ResolverMock.return_value.resolve.side_effect = resolve_side_effect
        post_mock.side_effect = requests.exceptions.ConnectionError("refused")

        report = diagnostics.diagnose(_record(target=LEGACY_TARGET))

        get_mock.assert_not_called()
        cf_check = next(c for c in report.checks if c.id == "cloudflare")
        self.assertEqual(cf_check.status, "skipped")
        self.assertFalse(any(c.remediation and c.remediation.type == "retry" for c in report.checks))
        self.assertEqual(report.summary.primary_issue, "live_event")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_cloudflare_missing_hostname_still_offers_retry(self, ResolverMock, get_mock, post_mock):
        # A genuine Cloudflare-path proxy whose custom hostname is missing: retry is correct.
        cname = MagicMock()
        cname.target.to_text.return_value = CF_TARGET

        def resolve_side_effect(name, rdtype):
            if rdtype == "CNAME":
                return [cname]
            raise dns.resolver.NoAnswer()

        ResolverMock.return_value.resolve.side_effect = resolve_side_effect
        post_mock.side_effect = requests.exceptions.ConnectionError("refused")
        get_mock.return_value = None

        report = diagnostics.diagnose(_record(target=CF_TARGET))

        cf_check = next(c for c in report.checks if c.id == "cloudflare")
        self.assertEqual(cf_check.status, "failed")
        assert cf_check.remediation is not None
        self.assertEqual(cf_check.remediation.type, "retry")

    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_cloudflare_unprovisioned_skips_hostname_check_when_dns_absent(self, ResolverMock, get_mock, post_mock):
        # A Cloudflare-path proxy whose DNS isn't set yet: we only create the custom hostname
        # after DNS resolves, so a missing hostname here is expected — not a fault. Skip the
        # check (not fail it), never call the Cloudflare API, and never suggest retry; the
        # missing CNAME is the real issue. Guards the false "we don't have a record of this
        # proxy → Hit Retry" that this record's lifecycle would otherwise surface.
        def resolve_side_effect(name, rdtype):
            if rdtype == "CNAME":
                raise dns.resolver.NXDOMAIN()
            raise dns.resolver.NoAnswer()

        ResolverMock.return_value.resolve.side_effect = resolve_side_effect

        report = diagnostics.diagnose(_record(target=CF_TARGET))

        post_mock.assert_not_called()
        get_mock.assert_not_called()
        cf_check = next(c for c in report.checks if c.id == "cloudflare")
        self.assertEqual(cf_check.status, "skipped")
        self.assertFalse(any(c.remediation and c.remediation.type == "retry" for c in report.checks))
        self.assertEqual(report.summary.primary_issue, "cname")

    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_cloudflare_not_serving_caa_blocking_is_primary(self, ResolverMock, get_mock, post_mock, http_get_mock):
        # CNAME query returns the right target; CAA query returns a blocking record.
        cname = MagicMock()
        cname.target.to_text.return_value = CF_TARGET

        def resolve_side_effect(name, rdtype):
            if rdtype == "CNAME":
                return [cname]
            if rdtype == "CAA":
                return [_caa_rdata(b"issue", "digicert.com")]
            raise dns.resolver.NoAnswer()

        ResolverMock.return_value.resolve.side_effect = resolve_side_effect
        post_mock.side_effect = requests.exceptions.ConnectionError("refused")
        get_mock.return_value = _hostname_info(ssl_status=CustomHostnameSSLStatus.PENDING_VALIDATION)
        http_get_mock.return_value = MagicMock(status_code=200, text="tok.body")

        report = diagnostics.diagnose(_record(target=CF_TARGET))

        self.assertEqual(report.summary.status, "fail")
        self.assertEqual(report.summary.primary_issue, "caa")
        # next_action is the fix (authorize pki.goog), not the cause
        self.assertIn("pki.goog", report.summary.next_action or "")

    @patch("posthog.api.proxy_record_diagnostics.ssl_module.create_default_context")
    @patch("posthog.api.proxy_record_diagnostics.socket.create_connection")
    @patch("posthog.api.proxy_record_diagnostics.requests.get")
    @patch("posthog.api.proxy_record_diagnostics.pinned_request")
    @patch("posthog.api.proxy_record_diagnostics.get_custom_hostname_by_domain")
    @patch("posthog.api.proxy_record_diagnostics.dns.resolver.Resolver")
    def test_stored_domain_that_is_not_a_hostname_never_reaches_the_network(
        self, ResolverMock, get_mock, post_mock, http_get_mock, socket_mock, _ctx_mock
    ):
        # `domain` predates write-time validation, and passing the CNAME check does not
        # constrain it: dnspython reads this as the DNS name `169.254.169.254:80/pad`
        # `.attacker.example`, so a nameserver the attacker controls can answer it with the
        # expected target, while `requests` reads the same string as the authority
        # `169.254.169.254:80`. The two grammars disagree, so the record must fail closed
        # before any check queries DNS or opens a connection.
        cname = MagicMock()
        cname.target.to_text.return_value = CF_TARGET
        ResolverMock.return_value.resolve.return_value = [cname]
        # A probe that fires would succeed, so the assertions below turn on whether it
        # fired at all rather than on how a half-configured mock happens to fail.
        post_mock.return_value = MagicMock(status_code=200)

        report = diagnostics.diagnose(_record(domain="169.254.169.254:80/pad.attacker.example", target=CF_TARGET))

        post_mock.assert_not_called()
        http_get_mock.assert_not_called()
        socket_mock.assert_not_called()
        get_mock.assert_not_called()
        ResolverMock.return_value.resolve.assert_not_called()
        self.assertEqual(report.summary.status, "fail")
        self.assertFalse(any(c.status == "passed" for c in report.checks))
