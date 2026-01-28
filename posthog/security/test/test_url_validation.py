import ipaddress

import pytest

from posthog.security import url_validation as uv


@pytest.fixture(autouse=True)
def force_prod(monkeypatch):
    # Ensure tests run with production-like SSRF behavior unless overridden in a test
    monkeypatch.setattr(uv, "is_dev_mode", lambda: False)


class TestUrlValidation:
    def test_is_url_allowed_disallowed_scheme(self):
        ok, err = uv.is_url_allowed("javascript:alert(1)")
        assert not ok and "scheme" in (err or "")

    def test_is_url_allowed_localhost(self):
        ok, err = uv.is_url_allowed("http://localhost")
        assert not ok and "Local" in (err or "")

    def test_is_url_allowed_loopback_ip(self):
        ok, err = uv.is_url_allowed("http://127.0.0.1")
        assert not ok and "Loopback" in (err or "")

    def test_is_url_allowed_metadata_host(self):
        ok, err = uv.is_url_allowed("http://169.254.169.254/latest/meta-data/")
        assert not ok and "Local/metadata" in (err or "")

    def test_dev_mode_allows_everything(self, monkeypatch):
        monkeypatch.setattr(uv, "is_dev_mode", lambda: True)
        ok, err = uv.is_url_allowed("http://localhost")
        assert ok and err is None
        assert uv.should_block_url("http://localhost/x") is False

    def test_is_url_allowed_private_resolution_blocked(self, monkeypatch):
        def fake_resolve(host: str):
            return {ipaddress.ip_address("192.168.1.10")}

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        ok, err = uv.is_url_allowed("https://example.com")
        assert not ok and "Disallowed target IP" in (err or "")

    def test_is_url_allowed_public_resolution_allowed(self, monkeypatch):
        def fake_resolve(host: str):
            return {ipaddress.ip_address("93.184.216.34")}  # example.com public IP

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        ok, err = uv.is_url_allowed("https://example.com/path")
        assert ok and err is None

    @pytest.mark.parametrize(
        "url,blocked",
        [
            ("http://example.com", False),
            ("https://example.com/a", False),
            ("http://localhost/x", True),
            ("http://127.0.0.1/x", True),
            ("http://192.168.0.2/x", True),
            ("http://10.0.0.5/x", True),
            ("http://169.254.0.5/x", True),
            ("http://172.16.0.1/x", True),
            ("http://172.20.0.1/x", True),
            ("http://172.31.255.255/x", True),
            ("http://172.15.255.255/x", False),  # not in RFC1918 range
            ("ftp://example.com", True),  # non-http(s)
            # Internal domain patterns (SSRF protection)
            ("http://service.svc.cluster.local/metrics", True),
            ("http://external-dns.kube-system.svc.cluster.local:7979/metrics", True),
            ("http://foo.internal/api", True),
            ("http://printer.local/status", True),
            ("http://db.consul/health", True),
            ("http://server.home.arpa/admin", True),
            ("http://intra.corp/dashboard", True),
            ("http://host.localdomain/page", True),
            ("http://device.lan/config", True),
            ("http://nas.home/files", True),
            ("http://server.priv/admin", True),
            ("http://app.intranet/login", True),
            # IPv6 addresses
            ("http://[::1]/", True),  # IPv6 loopback
            ("http://[fe80::1]/", True),  # IPv6 link-local
            ("http://[fd00::1]/", True),  # IPv6 unique local (private)
            ("http://[fc00::1]/", True),  # IPv6 unique local (private)
            ("http://[::ffff:127.0.0.1]/", True),  # IPv4-mapped IPv6 loopback
            ("http://[::ffff:192.168.1.1]/", True),  # IPv4-mapped IPv6 private
            ("http://[::ffff:10.0.0.1]/", True),  # IPv4-mapped IPv6 private
            ("http://[2001:db8::1]/", True),  # Documentation/reserved range
            ("http://[ff02::1]/", True),  # IPv6 multicast
        ],
    )
    def test_should_block_url(self, url, blocked):
        assert uv.should_block_url(url) is blocked

    def test_should_block_url_hostname_resolves_to_private_ip(self, monkeypatch):
        def fake_resolve(host: str):
            if host == "attacker-controlled.com":
                return {ipaddress.ip_address("10.0.0.5")}
            return {ipaddress.ip_address("93.184.216.34")}

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        assert uv.should_block_url("http://attacker-controlled.com/evil") is True
        assert uv.should_block_url("http://example.com/safe") is False

    def test_is_url_allowed_empty_dns_resolution_blocked(self, monkeypatch):
        """URLs with unresolvable hostnames should be blocked (fail-closed)."""

        def empty_resolve(host: str):
            return set()

        monkeypatch.setattr(uv, "resolve_host_ips", empty_resolve)
        ok, err = uv.is_url_allowed("https://unresolvable-host.example/")
        assert not ok
        assert err == "Could not resolve host"

    def test_should_block_url_empty_dns_resolution_blocked(self, monkeypatch):
        """should_block_url should block URLs with unresolvable hostnames."""

        def empty_resolve(host: str):
            return set()

        monkeypatch.setattr(uv, "resolve_host_ips", empty_resolve)
        assert uv.should_block_url("http://unresolvable-host.example/") is True

    @pytest.mark.parametrize(
        "url,expected_blocked,description",
        [
            # Decimal IP encoding (127.0.0.1 = 2130706433)
            ("http://2130706433/", True, "Decimal encoding of 127.0.0.1"),
            # Decimal IP encoding (192.168.0.1 = 3232235521)
            ("http://3232235521/", True, "Decimal encoding of 192.168.0.1"),
            # Hex IP encoding (127.0.0.1 = 0x7f000001)
            ("http://0x7f000001/", True, "Hex encoding of 127.0.0.1"),
            # Hex IP encoding (192.168.0.1 = 0xc0a80001)
            ("http://0xc0a80001/", True, "Hex encoding of 192.168.0.1"),
            # Dotted hex (127.0.0.1)
            ("http://0x7f.0.0.1/", True, "Dotted hex encoding of 127.0.0.1"),
        ],
    )
    def test_encoded_ip_addresses_blocked(self, url, expected_blocked, description):
        """Encoded IP addresses (decimal, hex) should be blocked via DNS resolution."""
        assert uv.should_block_url(url) is expected_blocked, description

    @pytest.mark.parametrize(
        "url,expected_blocked,description",
        [
            # Punycode domain that resolves to private IP
            ("http://xn--n3h.com/", True, "Punycode domain resolving to private IP"),
            # IDN domain with Cyrillic characters (homograph attack)
            ("http://xn--pple-43d.com/", True, "IDN homograph domain resolving to private IP"),
        ],
    )
    def test_idn_punycode_domains_blocked_via_resolution(self, monkeypatch, url, expected_blocked, description):
        """IDN/Punycode domains should be blocked if they resolve to private IPs."""

        def fake_resolve(host: str):
            # Simulate these domains resolving to private IPs (attack scenario)
            return {ipaddress.ip_address("10.0.0.1")}

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        assert uv.should_block_url(url) is expected_blocked, description

    def test_idn_domain_allowed_if_resolves_to_public_ip(self, monkeypatch):
        """IDN domains should be allowed if they resolve to public IPs."""

        def fake_resolve(host: str):
            return {ipaddress.ip_address("93.184.216.34")}  # Public IP

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        ok, err = uv.is_url_allowed("http://xn--n3h.com/")
        assert ok and err is None
