import ipaddress

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests.adapters import HTTPAdapter

from posthog.security import pinned_requests as pr


class TestPinnedRequest:
    def test_blocked_url_raises_before_any_connection(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(False, "Loopback host", set())),
            patch.object(pr.requests, "Session") as session_cls,
        ):
            with pytest.raises(pr.SSRFBlockedError, match="Loopback host"):
                pr.pinned_request("GET", "http://127.0.0.1/admin", timeout=5)
        session_cls.assert_not_called()


class TestSelectPinnedIP:
    # Pinning replaces the resolver's address selection, so picking an AAAA record when an A
    # record exists strands the request on any IPv4-only host ("Network is unreachable") instead
    # of falling back. That is what IPv4-only CI runners do, and it fails the whole request.
    @pytest.mark.parametrize(
        "ips,expected",
        [
            ({"2600:1f18::1", "93.184.216.34"}, "93.184.216.34"),
            ({"93.184.216.34"}, "93.184.216.34"),
            ({"2600:1f18::1"}, "2600:1f18::1"),
            # Deterministic within a family, so a broken pin reproduces instead of flapping.
            ({"93.184.216.34", "10.1.1.1", "203.0.113.9"}, "10.1.1.1"),
        ],
    )
    def test_prefers_ipv4_and_is_deterministic(self, ips, expected):
        chosen = pr.select_pinned_ip({ipaddress.ip_address(ip) for ip in ips})
        assert chosen == ipaddress.ip_address(expected)

    def test_empty_set_pins_nothing(self):
        assert pr.select_pinned_ip(set()) is None


class TestPinnedIPAdapter:
    @pytest.mark.parametrize(
        "ip,expected_netloc",
        [
            ("93.184.216.34", "93.184.216.34:8443"),
            ("2001:db8::1", "[2001:db8::1]:8443"),
        ],
    )
    def test_rewrites_url_to_pinned_ip_and_preserves_host_header(self, ip, expected_netloc):
        adapter = pr.PinnedIPAdapter()
        adapter.pin("Example.COM", ipaddress.ip_address(ip))
        request = requests.Request("GET", "https://example.com:8443/path?q=1").prepare()

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()):
            adapter.send(request)

        assert request.url == f"https://{expected_netloc}/path?q=1"
        assert request.headers["Host"] == "example.com:8443"

    def test_idn_host_still_matches_its_pin(self):
        # requests IDNA-encodes the host before send(), so the pin must be stored
        # under the same encoded form or the request silently re-resolves DNS —
        # the rebinding bypass this adapter exists to prevent.
        adapter = pr.PinnedIPAdapter()
        adapter.pin("éxample.com", ipaddress.ip_address("93.184.216.34"))
        request = requests.Request("GET", "https://éxample.com/path").prepare()
        assert "xn--xample-9ua.com" in (request.url or "")  # requests already punycoded it

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()):
            adapter.send(request)

        assert request.url == "https://93.184.216.34/path"
        assert request.headers["Host"] == "xn--xample-9ua.com"

    def test_unmatched_host_is_refused(self):
        # A pinned adapter that can't match the outgoing host must fail closed
        # rather than let requests re-resolve DNS to an unvalidated address.
        adapter = pr.PinnedIPAdapter()
        adapter.pin("example.com", ipaddress.ip_address("93.184.216.34"))
        request = requests.Request("GET", "https://other.example.org/path").prepare()

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()) as inner_send:
            with pytest.raises(pr.SSRFBlockedError):
                adapter.send(request)
        inner_send.assert_not_called()

    def test_no_pins_passes_through(self):
        # Empty map means pinning was intentionally skipped (dev SSRF bypass);
        # fail-closed must not fire there or local requests break.
        adapter = pr.PinnedIPAdapter()
        request = requests.Request("GET", "https://other.example.org/path").prepare()

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()):
            adapter.send(request)

        assert request.url == "https://other.example.org/path"
        assert "Host" not in request.headers
