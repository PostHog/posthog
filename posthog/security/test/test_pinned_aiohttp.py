import os
import ssl
import socket
import asyncio
import ipaddress

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.test import override_settings

import aiohttp

from posthog.security.pinned_aiohttp import PinnedResolver, pinned_session
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import ResolvedIPs

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")
PROXY_URL = "http://proxy.example.com:3128"


class ConnectionIntercepted(Exception):
    pass


@pytest.fixture(autouse=True)
def clear_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,host,address,host_header",
    [
        ("https://example.com:8443/path", "example.com", PUBLIC_IP, "example.com:8443"),
        ("https://éxample.com./path", "xn--xample-9ua.com", PUBLIC_IP, "xn--xample-9ua.com"),
        ("http://93.184.216.34/path", "93.184.216.34", PUBLIC_IP, "93.184.216.34"),
        ("https://example.com/path", "example.com", ipaddress.ip_address("2001:4860:4860::8888"), "example.com"),
    ],
)
async def test_direct_connections_keep_pins_and_tls_identity(
    url: str, host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address, host_header: str
) -> None:
    with (
        patch("aiohttp.connector.DefaultResolver.resolve", side_effect=AssertionError("Unexpected DNS lookup")),
        patch("aiohttp.TCPConnector._wrap_create_connection", side_effect=ConnectionIntercepted) as connect,
    ):
        async with pinned_session({host: {address}}) as client:
            with pytest.raises(ConnectionIntercepted):
                await client.get(url)

    connect.assert_awaited_once()
    kwargs = connect.call_args.kwargs
    assert kwargs["addr_infos"][0][4][0] == str(address)
    request = kwargs["req"]
    assert request.headers["Host"] == host_header
    if request.url.scheme == "https":
        assert kwargs["server_hostname"] == host
        assert kwargs["ssl"].verify_mode == ssl.CERT_REQUIRED
        assert kwargs["ssl"].check_hostname


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize(
    "url,environment,explicit_proxy,proxied",
    [
        ("https://example.com/", {}, None, False),
        ("https://example.com/", {"HTTPS_PROXY": PROXY_URL}, None, True),
        ("http://example.com/", {"HTTP_PROXY": PROXY_URL}, None, True),
        ("https://example.com/", {"HTTPS_PROXY": PROXY_URL, "NO_PROXY": "example.com"}, None, False),
        ("https://example.com/", {}, PROXY_URL, True),
    ],
)
async def test_proxy_routing(
    url: str,
    environment: dict[str, str],
    explicit_proxy: str | None,
    proxied: bool,
    pinned: bool,
) -> None:
    with (
        patch.dict(os.environ, environment),
        patch(
            "aiohttp.connector.DefaultResolver.resolve",
            return_value=[
                {
                    "hostname": "proxy.example.com" if proxied else "example.com",
                    "host": "10.0.0.2" if proxied else "127.0.0.1",
                    "port": 3128 if proxied else 443,
                    "family": socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            ],
        ) as resolve,
        patch("aiohttp.TCPConnector._wrap_create_connection", side_effect=ConnectionIntercepted) as connect,
    ):
        async with pinned_session({"example.com": {PUBLIC_IP}} if pinned else {}) as client:
            with pytest.raises(ConnectionIntercepted):
                await client.get(url, proxy=explicit_proxy)

    expected_address = "10.0.0.2" if proxied else (str(PUBLIC_IP) if pinned else "127.0.0.1")
    assert connect.call_args.kwargs["addr_infos"][0][4][0] == expected_address
    if proxied or not pinned:
        resolve.assert_awaited_once()
        assert resolve.call_args.args[0] == ("proxy.example.com" if proxied else "example.com")
    else:
        resolve.assert_not_awaited()


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("proxy", ["http://proxy.example.com:3129", "http://other.example.com:3128"])
async def test_untrusted_proxy_is_rejected_before_connecting(proxy: str, pinned: bool) -> None:
    with patch("aiohttp.TCPConnector.connect", side_effect=AssertionError("Unexpected connection")) as connect:
        async with pinned_session({"example.com": {PUBLIC_IP}} if pinned else {}) as client:
            with pytest.raises(SSRFBlockedError, match="proxy"):
                await client.get("https://example.com/", proxy=proxy, headers={"Authorization": "Bearer fake-token"})
    connect.assert_not_awaited()


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
@pytest.mark.parametrize("proxy", [None, PROXY_URL])
@pytest.mark.parametrize(
    "target,allowed", [("/continued", True), ("https://other.example.com/", False), ("http://169.254.169.254/", False)]
)
async def test_redirects_only_reuse_validated_hosts(proxy: str | None, target: str, allowed: bool) -> None:
    response = Mock(spec=aiohttp.ClientResponse)
    response.status = 302
    response.method = "GET"
    response.headers = {"Location": target}
    response._raw_cookie_headers = ()
    response.start = AsyncMock()

    with (
        patch("aiohttp.TCPConnector.connect", return_value=Mock()) as connect,
        patch("aiohttp.ClientRequest.send", side_effect=[response, ConnectionIntercepted]) as send,
    ):
        async with pinned_session({"example.com": {PUBLIC_IP}}) as client:
            with pytest.raises(ConnectionIntercepted if allowed else SSRFBlockedError):
                await client.get("https://example.com/", proxy=proxy)

    assert connect.await_count == (2 if allowed else 1)
    assert send.await_count == (2 if allowed else 1)


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
async def test_proxy_tunnel_keeps_tls_hostname_and_verification() -> None:
    proxy_response = Mock(spec=aiohttp.ClientResponse)
    proxy_response.status = 200
    proxy_response.start = AsyncMock(return_value=proxy_response)
    transport = Mock(spec=asyncio.Transport)
    transport.get_extra_info.return_value = None

    with (
        patch(
            "aiohttp.connector.DefaultResolver.resolve",
            return_value=[
                {
                    "hostname": "proxy.example.com",
                    "host": "10.0.0.2",
                    "port": 3128,
                    "family": socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            ],
        ),
        patch("aiohttp.TCPConnector._wrap_create_connection", return_value=(transport, Mock())),
        patch("aiohttp.ClientRequest.send", return_value=proxy_response),
        patch.object(
            asyncio.get_running_loop(), "start_tls", side_effect=ssl.SSLCertVerificationError("Rejected certificate")
        ) as start_tls,
    ):
        async with pinned_session({"example.com": {PUBLIC_IP}}) as client:
            with pytest.raises(aiohttp.ClientConnectorCertificateError):
                await client.get("https://example.com/", proxy=PROXY_URL)

    start_tls.assert_awaited_once()
    assert start_tls.call_args.kwargs["server_hostname"] == "example.com"
    context = start_tls.call_args.args[2]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
async def test_proxy_rejection_does_not_fall_back_to_direct() -> None:
    error = aiohttp.ClientHttpProxyError(Mock(), (), status=403, message="Forbidden")
    with (
        patch("aiohttp.TCPConnector._create_proxy_connection", side_effect=error) as proxy_connect,
        patch(
            "aiohttp.TCPConnector._create_direct_connection", side_effect=AssertionError("Unexpected fallback")
        ) as direct,
    ):
        async with pinned_session({"example.com": {PUBLIC_IP}}) as client:
            with pytest.raises(aiohttp.ClientHttpProxyError):
                await client.get("https://example.com/", proxy=PROXY_URL)

    proxy_connect.assert_awaited_once()
    direct.assert_not_awaited()


@pytest.mark.asyncio
@override_settings(SSRF_TRUSTED_PROXY_URLS=[PROXY_URL])
@pytest.mark.parametrize("proxy", [None, PROXY_URL])
@pytest.mark.parametrize("pins", [{"example.com": set()}, {"other.example.com": {PUBLIC_IP}}])
async def test_missing_pins_reject_before_connecting(pins: dict[str, ResolvedIPs], proxy: str | None) -> None:
    with pytest.raises(SSRFBlockedError):
        await PinnedResolver(pins).resolve("example.com", 443)

    with patch("aiohttp.TCPConnector.connect", side_effect=AssertionError("Unexpected connection")) as connect:
        async with pinned_session(pins) as client:
            with pytest.raises(SSRFBlockedError):
                await client.get("https://example.com/", proxy=proxy)

    connect.assert_not_awaited()
