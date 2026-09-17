import os
import ipaddress

import pytest
from unittest.mock import patch

import httpx

from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")


def _capturing_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    return httpx.MockTransport(handler)


def _without_environment_proxies() -> dict[str, str]:
    return {key: "" for key in os.environ if key.lower().endswith("_proxy")}


class TestPinnedTransport:
    @pytest.mark.parametrize(
        "url,ip,expected_url,expected_host_header,expected_sni",
        [
            (
                "https://Example.com:8443/path?q=1",
                "93.184.216.34",
                "https://93.184.216.34:8443/path?q=1",
                "example.com:8443",
                "example.com",
            ),
            ("https://example.com/path", "2001:db8::1", "https://[2001:db8::1]/path", "example.com", "example.com"),
            # httpx punycodes the host before the transport sees it, so the pin must match that form.
            (
                "https://éxample.com./path",
                "93.184.216.34",
                "https://93.184.216.34/path",
                "xn--xample-9ua.com.",
                "xn--xample-9ua.com",
            ),
            ("http://example.com/path", "93.184.216.34", "http://93.184.216.34/path", "example.com", None),
        ],
    )
    def test_connects_to_the_pinned_address_and_keeps_the_host_name(
        self, url, ip, expected_url, expected_host_header, expected_sni
    ):
        seen: list[httpx.Request] = []
        client = pinned_client(url, {ipaddress.ip_address(ip)}, transport=_capturing_transport(seen), trust_env=False)

        client.get(url)

        [request] = seen
        assert str(request.url) == expected_url
        assert request.headers["Host"] == expected_host_header
        assert request.extensions.get("sni_hostname") == expected_sni

    def test_refuses_a_host_that_was_not_pinned(self):
        seen: list[httpx.Request] = []
        client = pinned_client(
            "https://example.com/", {PUBLIC_IP}, transport=_capturing_transport(seen), trust_env=False
        )

        with pytest.raises(SSRFBlockedError):
            client.get("https://other.example.com/")
        assert seen == []

    def test_nothing_pinned_passes_the_request_through(self):
        seen: list[httpx.Request] = []
        client = pinned_client("https://example.com/", set(), transport=_capturing_transport(seen), trust_env=False)

        client.get("https://other.example.com/")

        assert str(seen[0].url) == "https://other.example.com/"


class TestPinnedClientRouting:
    # httpx picks the transport for a URL before the pinned one sees the request. A proxied
    # request must keep its host name, because the CONNECT tunnel verifies the certificate
    # against the connect target.
    @pytest.mark.parametrize(
        "environment,expected_host",
        [
            ({}, "93.184.216.34"),
            ({"HTTPS_PROXY": "http://egress.example:3128"}, "example.com"),
        ],
    )
    def test_pins_direct_connections_only(self, environment, expected_host):
        seen: list[httpx.Request] = []

        def handle_request(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        with (
            patch.dict(os.environ, {**_without_environment_proxies(), **environment}),
            patch.object(httpx.HTTPTransport, "handle_request", handle_request),
        ):
            client = pinned_client("https://example.com/", {PUBLIC_IP}, trust_env=True)
            client.get("https://example.com/")

        [request] = seen
        assert request.url.host == expected_host
