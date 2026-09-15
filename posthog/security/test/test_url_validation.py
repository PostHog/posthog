import ipaddress
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, BoundedSemaphore

import pytest

from posthog.security import url_validation as uv


@pytest.fixture(autouse=True)
def force_prod(monkeypatch):
    # Ensure tests run with production-like SSRF behavior unless overridden in a test
    monkeypatch.setattr(uv, "is_dev_mode", lambda: False)


@pytest.fixture
def enforce_destination_validation(settings):
    # By default, we bypass URL and host validation in tests. We want to test the validation
    # logic, so we opt back in.
    settings.FORCE_URL_VALIDATION = True


class TestUrlValidation:
    def test_resolve_host_ips_uses_bounded_lifetime(self, monkeypatch):
        class Answers:
            def addresses(self):
                return iter(["93.184.216.34"])

        class Resolver:
            def resolve_name(self, host, *, lifetime):
                assert host == "example.com"
                assert lifetime == uv.DNS_RESOLUTION_LIFETIME_SECONDS
                return Answers()

        monkeypatch.setattr(uv.dns.resolver, "Resolver", Resolver)

        assert uv.resolve_host_ips("example.com") == {ipaddress.ip_address("93.184.216.34")}

    def test_resolve_host_ips_resolves_an_idn_host_but_not_a_url(self, monkeypatch):
        # Every other test replaces resolve_host_ips itself, so nothing else runs a real host
        # string through its shape gate. The gate has to admit an internationalized name, whose
        # punycode form is a hostname, while still keeping a URL away from the resolver.
        queried: list[str] = []

        class Answers:
            def addresses(self):
                return iter(["93.184.216.34"])

        class Resolver:
            def resolve_name(self, host, *, lifetime):
                queried.append(host)
                return Answers()

        monkeypatch.setattr(uv.dns.resolver, "Resolver", Resolver)

        assert uv.resolve_host_ips("münchen.de") == {ipaddress.ip_address("93.184.216.34")}
        assert uv.resolve_host_ips("postgresql://db.example.com:5432/analytics") == set()
        assert queried == ["münchen.de"]

    def test_resolve_url_hosts_ips_deduplicates_hosts(self, monkeypatch):
        def fake_resolve_hosts_ips(hosts):
            assert hosts == {"shared.example.com"}
            return {"shared.example.com": {ipaddress.ip_address("93.184.216.34")}}

        monkeypatch.setattr(uv, "resolve_hosts_ips", fake_resolve_hosts_ips)

        assert uv.resolve_url_hosts_ips(["https://shared.example.com/first", "https://shared.example.com/second"]) == {
            "shared.example.com": {ipaddress.ip_address("93.184.216.34")}
        }

    def test_resolve_hosts_ips_stops_at_batch_deadline(self, monkeypatch):
        pending_future: Future[uv.ResolvedIPs] = Future()

        class Executor:
            def submit(self, _function, _host):
                return pending_future

        monkeypatch.setattr(uv, "_dns_resolution_executor", Executor())
        monkeypatch.setattr(uv, "DNS_RESOLUTION_BATCH_TIMEOUT_SECONDS", 0)

        assert uv.resolve_hosts_ips({"slow.example.com"}) == {"slow.example.com": set()}
        assert pending_future.cancelled()

    def test_resolve_hosts_ips_starts_all_allowed_hosts_within_the_batch_deadline(self, monkeypatch):
        hosts = {f"host-{index}.example.com" for index in range(20)}
        all_workers_started = Barrier(len(hosts))
        public_ip = ipaddress.ip_address("93.184.216.34")

        def resolve_after_all_workers_start(_host):
            all_workers_started.wait(timeout=1)
            return {public_ip}

        executor = ThreadPoolExecutor(max_workers=uv.DNS_RESOLUTION_MAX_WORKERS)
        monkeypatch.setattr(uv, "_dns_resolution_executor", executor)
        monkeypatch.setattr(uv, "resolve_host_ips", resolve_after_all_workers_start)

        try:
            assert uv.resolve_hosts_ips(hosts) == {host: {public_ip} for host in hosts}
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def test_resolve_hosts_ips_fails_closed_when_global_capacity_is_exhausted(self, monkeypatch):
        capacity = BoundedSemaphore(1)
        capacity.acquire()

        class Executor:
            def submit(self, _function, _host):
                raise AssertionError("capacity exhaustion must prevent queueing")

        monkeypatch.setattr(uv, "_dns_resolution_capacity", capacity)
        monkeypatch.setattr(uv, "_dns_resolution_executor", Executor())

        assert uv.resolve_hosts_ips({"busy.example.com"}) == {"busy.example.com": set()}

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "not-a-url",
        ],
    )
    def test_is_url_allowed_rejects_anything_that_is_not_http(self, url):
        ok, err = uv.is_url_allowed(url)
        assert not ok
        assert "must start with http" in (err or "")

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

    def test_force_url_validation_setting_disables_dev_bypass(self, monkeypatch, settings):
        monkeypatch.setattr(uv, "is_dev_mode", lambda: True)
        settings.FORCE_URL_VALIDATION = True
        ok, err = uv.is_url_allowed("http://localhost")
        assert not ok and "Loopback" in (err or "")

    def test_force_url_validation_setting_off_keeps_dev_bypass(self, monkeypatch, settings):
        monkeypatch.setattr(uv, "is_dev_mode", lambda: True)
        settings.FORCE_URL_VALIDATION = False
        ok, err = uv.is_url_allowed("http://localhost")
        assert ok and err is None

    @pytest.mark.parametrize(
        "resolved_ips, expected_error",
        [
            # An internal IP and a host that does not resolve report the same thing on purpose,
            # so the error cannot be used to find which addresses exist inside our network.
            ({ipaddress.ip_address("10.0.0.1")}, "does not resolve to a valid IP address"),
            (set(), "does not resolve to a valid IP address"),
            ({ipaddress.ip_address("93.184.216.34")}, None),
        ],
    )
    def test_validate_external_host_enforced(
        self, monkeypatch, enforce_destination_validation, resolved_ips, expected_error
    ):
        # This path resolves and judges IPs itself rather than calling is_url_allowed, so the
        # cases above do not cover it. A host that resolves to no IPs is rejected, because
        # there is then nothing to judge it by.
        monkeypatch.setattr(uv, "resolve_host_ips", lambda host: resolved_ips)
        if expected_error is None:
            uv.validate_external_host("db.example.com")
        else:
            with pytest.raises(ValueError, match=expected_error):
                uv.validate_external_host("db.example.com")

    @pytest.mark.parametrize(
        "url, resolved_ip, should_raise",
        [
            ("http://127.0.0.1", None, True),
            ("https://example.com", "93.184.216.34", False),
        ],
    )
    def test_validate_external_url_enforced(
        self, monkeypatch, enforce_destination_validation, url, resolved_ip, should_raise
    ):
        # This path takes its rules from is_url_allowed, so what is under test is the
        # translation of its verdict: a blocked one has to raise, an allowed one has to return.
        if resolved_ip is not None:
            monkeypatch.setattr(uv, "resolve_host_ips", lambda host: {ipaddress.ip_address(resolved_ip)})
        if should_raise:
            with pytest.raises(ValueError):
                uv.validate_external_url(url)
        else:
            uv.validate_external_url(url)

    @pytest.mark.parametrize(
        "dev_mode, test_mode, force, bypassed",
        [
            (True, False, False, True),  # local dev
            (False, True, False, True),  # in tests
            (False, True, True, False),  # override using FORCE_URL_VALIDATION
            (False, False, False, False),  # production
        ],
    )
    def test_validate_external_url_and_host_bypass_validation_only_in_dev_and_test(
        self, monkeypatch, settings, dev_mode, test_mode, force, bypassed
    ):
        monkeypatch.setattr(uv, "is_dev_mode", lambda: dev_mode)
        settings.TEST = test_mode
        settings.FORCE_URL_VALIDATION = force

        if bypassed:
            uv.validate_external_host("10.0.0.1")
            uv.validate_external_url("http://localhost:9000")
        else:
            with pytest.raises(ValueError):
                uv.validate_external_host("10.0.0.1")
            with pytest.raises(ValueError):
                uv.validate_external_url("http://localhost:9000")

    @pytest.mark.parametrize(
        "host, expected_reason",
        [
            ("db.corp", "Internal domain pattern blocked"),  # the suffix loop
            ("metadata.google.internal", "Local/metadata host"),  # exact match, a separate branch
            # The suffix match is case sensitive, and canonicalization lowercases first.
            ("DB.CORP", "Internal domain pattern blocked"),
            ("db.corp.", "Internal domain pattern blocked"),  # a root dot must not hide a suffix
            ("localhost.", "Local/Loopback host not allowed"),  # nor an exact match
            # The whole of 127.0.0.0/8 is loopback, not just 127.0.0.1. Caught by parsing the
            # address, so no DNS lookup happens and every long form is caught the same way.
            ("127.0.0.2", "Private IP address not allowed"),
            # IDNA maps fullwidth characters onto ASCII ones, so this is the resolver's
            # "evil.corp". The name checks have to see the form the resolver will query.
            ("ｅｖｉｌ．ｃｏｒｐ", "Internal domain pattern blocked"),
            ("ｌｏｃａｌｈｏｓｔ", "Local/Loopback host not allowed"),
        ],
    )
    def test_host_and_url_paths_agree_on_internal_names(self, enforce_destination_validation, host, expected_reason):
        with pytest.raises(ValueError, match=expected_reason):
            uv.validate_external_host(host)
        allowed, reason = uv.is_url_allowed(f"https://{host}")
        assert not allowed
        assert expected_reason in (reason or "")

    @pytest.mark.parametrize(
        "validate, value",
        [
            (uv.validate_external_url, "not-a-url"),
            (uv.validate_external_url, "javascript:alert(1)"),
            (uv.validate_external_url, "ftp://internal"),
            (uv.validate_external_url, "https://"),
            (uv.validate_external_host, ""),
            (uv.validate_external_host, "   "),
        ],
    )
    def test_malformed_target_is_rejected_even_where_validation_is_bypassed(self, validate, value):
        # No enforce_destination_validation here on purpose; the form of a target does not
        # depend on the environment.
        with pytest.raises(ValueError):
            validate(value)

    @pytest.mark.parametrize(
        "host, usable",
        [
            ("db.example.com", True),
            ("8.8.8.8", True),
            # A bare IPv6 literal is a host, and its colons are not a path. It has to be a
            # globally routable one, because the name check rejects every internal address.
            ("2606:4700:4700::1111", True),
            ("10.example.com", True),  # a name that starts like a private range is still a name
            ("db.example.com.", True),  # the root dot of an absolute FQDN
            ("db.acme.com:5432", False),
            ("user@db.acme.com", False),
            ("http://db.acme.com", False),
        ],
    )
    def test_host_field_takes_a_hostname_or_ip_only(self, enforce_destination_validation, monkeypatch, host, usable):
        monkeypatch.setattr(uv, "resolve_host_ips", lambda _host: {ipaddress.ip_address("93.184.216.34")})
        if usable:
            uv.validate_external_host(host)
        else:
            with pytest.raises(ValueError, match="hostname or IP address"):
                uv.validate_external_host(host)

    @pytest.mark.parametrize("value", [None, 123])
    def test_non_string_target_is_a_client_error(self, value):
        # A non-string has to read as bad input rather than surface as a TypeError
        with pytest.raises(ValueError):
            uv.validate_external_host(value)
        with pytest.raises(ValueError):
            uv.validate_external_url(value)

    @pytest.mark.parametrize(
        "resolved_ip",
        [
            "192.168.1.10",
            # CGNAT (RFC 6598): neither is_private nor is_global, so the attribute flags
            # alone let it through; guards the explicit _CGNAT_NETWORK check.
            "100.64.0.1",
            "100.127.255.255",
            # IPv4-mapped form of a CGNAT address, which network membership alone misses.
            "::ffff:100.64.0.1",
        ],
    )
    def test_is_url_allowed_private_resolution_blocked(self, resolved_ip, monkeypatch):
        def fake_resolve(host: str):
            return {ipaddress.ip_address(resolved_ip)}

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
        "url",
        [
            "https://user%40corp.example:pass@example.com/path",
            "https://user:p%2Fss@example.com/path",
            "https://user:p%3Fss@example.com/path",
            "https://user:p%23ss@example.com/path",
        ],
    )
    def test_is_url_allowed_permits_percent_encoded_credentials(self, url, monkeypatch):
        # Integrations and warehouse sources supply connection URLs with basic auth, and an
        # email username or a password holding a reserved character has to percent-encode it.
        # Every parser resolves these to example.com, so the fetch path takes the lenient
        # rule. Swapping it for has_ambiguous_authority would break all of them.
        def fake_resolve(host: str):
            return {ipaddress.ip_address("93.184.216.34")}

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        ok, err = uv.is_url_allowed(url)
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

    @pytest.mark.parametrize(
        "url",
        [
            # urlparse extracts "example.com", but requests/urllib3 connect to 169.254.169.254.
            "http://169.254.169.254\\@example.com/latest/meta-data/",
            # Same trick, percent-encoded backslash. Browsers decode and follow to localhost.
            "http://localhost%5C@example.com/",
            "http://127.0.0.1\\@example.com/",
            "https://attacker.com\\@example.com/",
        ],
    )
    def test_backslash_authority_bypass_blocked(self, url, monkeypatch):
        """Backslash (raw or %5c) before @ breaks urlparse-vs-client agreement on the host."""

        def fake_resolve(host: str):
            return {ipaddress.ip_address("93.184.216.34")}

        monkeypatch.setattr(uv, "resolve_host_ips", fake_resolve)
        ok, err = uv.is_url_allowed(url)
        assert not ok
        assert err == "Invalid URL: ambiguous authority"

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("http://example.com/", False),
            ("http://example.com/path\\with-backslash", True),
            ("http://example.com%5Cpath", True),
            ("http://attacker.com\\@example.com", True),
            # Percent-encoded credentials are ordinary basic auth. Every parser resolves
            # these to example.com, so blocking them would break outbound fetches that
            # carry an email username or a password containing a reserved character.
            ("https://user%40corp.example:pass@example.com/path", False),
            ("https://user:p%2Fss@example.com/path", False),
            ("https://user:p%23ss@example.com/path", False),
        ],
    )
    def test_has_authority_bypass_chars(self, url, expected):
        assert uv.has_authority_bypass_chars(url) is expected

    @pytest.mark.parametrize(
        "url,expected",
        [
            # A consumer that percent-decodes before splitting the authority sees it end
            # at the terminator, landing on a different host than urlparse reports.
            ("https://example.com%2F@attacker.com/", True),
            ("https://example.com%3f@attacker.com/", True),
            ("https://example.com%23@attacker.com/", True),
            ("https://example.com%40@attacker.com/", True),
            ("https://example.com%2Fpath", True),
            # Credentials are legitimate on a fetch but not on a URL we hand back, and
            # the encoded characters in them are exactly what makes the authority
            # ambiguous, so the strict rule rejects them where the lenient one allows.
            ("https://user%40corp.example:pass@example.com/path", True),
            # The strict rule subsumes the backslash cases.
            ("http://attacker.com\\@example.com", True),
            ("http://example.com%5Cpath", True),
            ("https://example.com/", False),
            # The same sequences outside the authority are ordinary encoded data.
            ("https://example.com/repos/group%2Fproject", False),
            ("https://example.com/send?to=someone%40example.com", False),
            ("https://example.com/search#q=a%23b", False),
            # Unparseable authorities fail closed rather than raising.
            ("https://[::1", True),
            ("https://exa℀mple.com/", True),
        ],
    )
    def test_has_ambiguous_authority(self, url, expected):
        assert uv.has_ambiguous_authority(url) is expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://prod-25.westeurope.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x",
            "https://acme.webhook.office.com/webhookb2/guid@guid/IncomingWebhook/hash/guid",
            "https://europe.powerautomate.com/manual/paths/invoke",
            "https://prod-01.flow.microsoft.com/manual/paths/invoke",
            "https://acme.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/abc",
        ],
    )
    def test_accepts_microsoft_teams_webhook_url(self, url):
        assert uv.is_microsoft_teams_webhook_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Both hostnames are registrable by anyone and satisfy the unescaped-dot patterns in
            # the CDP Teams template. They must not satisfy these.
            "https://evilpowerautomate.com/x",
            "https://aaaflow-microsoft.com/y",
            "https://evil.example.com/logic.azure.com/workflows/abc",
            "https://logic.azure.com.evil.example.com/workflows/abc",
            "http://prod-25.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke",
            "https://prod-25.westeurope.logic.azure.com:8443/workflows/abc/triggers/manual/paths/invoke",
            "https://prod-25.westeurope.logic.azure.com/workflows/abc",
            "https://acme.webhook.office.com/webhookb2/guid",
            "https://acme.webhook.office.com/something-else/guid",
            "https://prod-25.westeurope.logic.azure.com\\@evil.example.com/workflows/abc/triggers/manual/paths/invoke",
            "definitely not a url",
            "",
            # `requests` would turn the userinfo into a Basic Authorization header on the send,
            # and the credential would live on in the stored subscription.
            "https://user:pass@prod-25.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke",
            "https://user@prod-25.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke",
        ],
    )
    def test_rejects_non_teams_webhook_url(self, url):
        assert uv.is_microsoft_teams_webhook_url(url) is False
