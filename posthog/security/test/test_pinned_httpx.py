import ipaddress

import pytest
from unittest.mock import MagicMock, patch

import httpx

from posthog.security import pinned_httpx as ph


class TestPinnedIPHTTPTransport:
    @pytest.mark.parametrize(
        "ip,expected_host",
        [
            ("93.184.216.34", "93.184.216.34"),
            ("2001:db8::1", "[2001:db8::1]"),
        ],
    )
    def test_dials_pinned_ip_while_keeping_hostname_for_host_header_and_tls(self, ip, expected_host):
        transport = ph.PinnedIPHTTPTransport()
        transport.pin("Example.COM", ipaddress.ip_address(ip))
        request = httpx.Request("GET", "https://example.com:8443/v1/models")

        with patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()):
            transport.handle_request(request)

        assert str(request.url) == f"https://{expected_host}:8443/v1/models"
        assert request.headers["Host"] == "example.com:8443"
        # Without this, TLS would be verified against the IP and every pinned request would fail.
        assert request.extensions["sni_hostname"] == "example.com"

    def test_refuses_a_host_it_did_not_pin(self):
        transport = ph.PinnedIPHTTPTransport()
        transport.pin("example.com", ipaddress.ip_address("93.184.216.34"))

        with patch.object(httpx.HTTPTransport, "handle_request") as inner:
            with pytest.raises(ph.SSRFBlockedError):
                transport.handle_request(httpx.Request("GET", "https://internal.example/"))
        inner.assert_not_called()

    def test_passes_through_when_nothing_was_pinned(self):
        transport = ph.PinnedIPHTTPTransport()

        with patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()) as inner:
            transport.handle_request(httpx.Request("GET", "https://example.com/"))

        inner.assert_called_once()


class TestPinnedTransport:
    def test_blocked_url_raises_before_any_transport_is_built(self):
        with patch.object(ph, "validate_url_and_pin_ips", return_value=(False, "Loopback host", set())):
            with pytest.raises(ph.SSRFBlockedError, match="Loopback host"):
                ph.pinned_transport("https://127.0.0.1/v1")

    def test_pins_the_validated_address(self):
        with patch.object(
            ph,
            "validate_url_and_pin_ips",
            return_value=(True, None, {ipaddress.ip_address("93.184.216.34")}),
        ):
            transport = ph.pinned_transport("https://example.com/v1")

        request = httpx.Request("GET", "https://example.com/v1/models")
        with patch.object(httpx.HTTPTransport, "handle_request", return_value=MagicMock()):
            transport.handle_request(request)

        assert request.url.host == "93.184.216.34"
