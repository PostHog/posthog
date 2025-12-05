import ipaddress

import pytest

from posthog.heatmaps import heatmaps_utils as us


@pytest.fixture(autouse=True)
def force_prod(monkeypatch):
    # Ensure tests run with production-like SSRF behavior unless overridden in a test
    monkeypatch.setattr(us, "is_dev_mode", lambda: False)


class TestUrlSafety:
    def test_is_url_allowed_disallowed_scheme(self):
        ok, err = us.is_url_allowed("javascript:alert(1)")
        assert not ok and "scheme" in (err or "")

    def test_is_url_allowed_localhost(self):
        ok, err = us.is_url_allowed("http://localhost")
        assert not ok and "Local" in (err or "")

    def test_is_url_allowed_loopback_ip(self):
        ok, err = us.is_url_allowed("http://127.0.0.1")
        assert not ok and "Loopback" in (err or "")

    def test_is_url_allowed_metadata_host(self):
        ok, err = us.is_url_allowed("http://169.254.169.254/latest/meta-data/")
        assert not ok and "Local/metadata" in (err or "")

    def test_dev_mode_allows_everything(self, monkeypatch):
        monkeypatch.setattr(us, "is_dev_mode", lambda: True)
        ok, err = us.is_url_allowed("http://localhost")
        assert ok and err is None
        assert us.should_block_url("http://localhost/x") is False

    def test_is_url_allowed_private_resolution_blocked(self, monkeypatch):
        def fake_resolve(host: str):
            return {ipaddress.ip_address("192.168.1.10")}

        monkeypatch.setattr(us, "resolve_host_ips", fake_resolve)
        ok, err = us.is_url_allowed("https://example.com")
        assert not ok and "Disallowed target IP" in (err or "")

    def test_is_url_allowed_public_resolution_allowed(self, monkeypatch):
        def fake_resolve(host: str):
            return {ipaddress.ip_address("93.184.216.34")}  # example.com public IP

        monkeypatch.setattr(us, "resolve_host_ips", fake_resolve)
        ok, err = us.is_url_allowed("https://example.com/path")
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
        ],
    )
    def test_should_block_url(self, url, blocked):
        assert us.should_block_url(url) is blocked
