import ipaddress

import pytest
from unittest.mock import MagicMock, patch

import httpx

from posthog.security import pinned_httpx as ph
from posthog.security.pinned_requests import SSRFBlockedError


def _pinned_transport(pins: dict[str, str]) -> tuple[ph.PinnedIPTransport, MagicMock]:
    inner = MagicMock(spec=httpx.BaseTransport)
    return ph.PinnedIPTransport(inner, pins), inner


class TestPinnedIPTransport:
    @pytest.mark.parametrize(
        "ip,expected_url",
        [
            ("93.184.216.34", "https://93.184.216.34:8443/mcp"),
            ("2001:db8::1", "https://[2001:db8::1]:8443/mcp"),
        ],
    )
    def test_connects_to_the_pinned_ip_under_the_original_hostname(self, ip, expected_url):
        transport, inner = _pinned_transport({"example.com": ip})

        transport.handle_request(httpx.Request("POST", "https://Example.com:8443/mcp"))

        sent = inner.handle_request.call_args.args[0]
        assert str(sent.url) == expected_url
        # The Host header and TLS keep naming the host, so the upstream server and its
        # certificate are still the ones the URL asked for.
        assert sent.headers["Host"] == "example.com:8443"
        assert sent.extensions["sni_hostname"] == "example.com"

    def test_idn_host_still_matches_its_pin(self):
        transport, inner = _pinned_transport({"xn--xample-9ua.com": "93.184.216.34"})

        transport.handle_request(httpx.Request("GET", "https://éxample.com/mcp"))

        assert str(inner.handle_request.call_args.args[0].url) == "https://93.184.216.34/mcp"

    def test_unpinned_host_is_refused(self):
        transport, inner = _pinned_transport({"example.com": "93.184.216.34"})

        with pytest.raises(SSRFBlockedError, match="No validated pin"):
            transport.handle_request(httpx.Request("GET", "https://other.example/mcp"))
        inner.handle_request.assert_not_called()


class TestPinnedHttpxClient:
    def test_request_to_a_rebound_host_reaches_the_validated_ip(self):
        client = ph.pinned_httpx_client("https://mcp.example.com/mcp", {ipaddress.ip_address("93.184.216.34")})

        with patch.object(httpx.HTTPTransport, "handle_request", return_value=httpx.Response(200)) as handle_request:
            client.send(client.build_request("POST", "https://mcp.example.com/mcp"))

        sent = handle_request.call_args.args[0]
        assert str(sent.url) == "https://93.184.216.34/mcp"
        assert sent.headers["Host"] == "mcp.example.com"

    def test_an_env_proxy_route_is_pinned_too(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:9999")

        client = ph.pinned_httpx_client(
            "https://mcp.example.com/mcp", {ipaddress.ip_address("93.184.216.34")}, trust_env=True
        )

        # Every route httpx would take has to carry the pin, or a proxied request would
        # resolve the hostname a second time and reopen the rebinding window.
        assert client._mounts
        assert all(isinstance(transport, ph.PinnedIPTransport) for transport in client._mounts.values())
        assert isinstance(client._transport, ph.PinnedIPTransport)

    def test_no_validated_ips_leaves_the_client_unpinned(self):
        client = ph.pinned_httpx_client("https://mcp.example.com/mcp", set())

        assert isinstance(client._transport, httpx.HTTPTransport)
