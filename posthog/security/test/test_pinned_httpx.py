import os
import ssl
import socket
import ipaddress

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import httpx
import httpcore

from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import validate_url_and_pin_ips

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")


def _capturing_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(httpx.Request(request.method, request.url, headers=request.headers, extensions=request.extensions))
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

    @pytest.mark.parametrize("redirect", [False, True])
    def test_preserves_host_only_cookies_across_requests_and_redirects(self, redirect: bool) -> None:
        url = "https://example.com/mcp"
        seen: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            seen.append(
                httpx.Request(request.method, request.url, headers=request.headers, extensions=request.extensions)
            )
            if len(seen) == 1:
                headers = {"Set-Cookie": "mcp_session=fake-session; Path=/; Secure"}
                if redirect:
                    headers["Location"] = "/continued"
                return httpx.Response(302 if redirect else 200, headers=headers)
            return httpx.Response(200)

        with pinned_client(url, {PUBLIC_IP}, transport=httpx.MockTransport(handle_request), trust_env=False) as client:
            response = client.get(url, follow_redirects=True)
            assert response.status_code == 200
            assert response.url == httpx.URL("https://example.com/continued" if redirect else url)
            assert [item.url for item in response.history] == ([httpx.URL(url)] if redirect else [])
            assert [cookie.domain for cookie in client.cookies.jar] == ["example.com"]
            assert client.get("https://example.com/continued").status_code == 200

        assert len(seen) == (3 if redirect else 2)
        assert {request.url.host for request in seen} == {str(PUBLIC_IP)}
        assert {request.headers["Host"] for request in seen} == {"example.com"}
        assert {request.extensions["sni_hostname"] for request in seen} == {"example.com"}
        assert seen[0].headers.get("Cookie") is None
        assert {request.headers.get("Cookie") for request in seen[1:]} == {"mcp_session=fake-session"}

    @pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
    def test_restores_request_url_after_transport_error(self, error_type: type[httpx.RequestError]) -> None:
        url = "https://example.com/mcp"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url.host == str(PUBLIC_IP)
            raise error_type("upstream failed", request=request)

        with pinned_client(url, {PUBLIC_IP}, transport=httpx.MockTransport(handle_request), trust_env=False) as client:
            request = client.build_request("GET", url)
            with pytest.raises(error_type) as error:
                client.send(request)
            assert request.url == httpx.URL(url)
            assert error.value.request.url == httpx.URL(url)


class TestPinnedClientRouting:
    @override_settings(SSRF_TRUSTED_PROXY_URLS=[])
    @pytest.mark.parametrize("proxy_variable", ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"])
    def test_refuses_untrusted_proxy_before_sending_credentials(self, proxy_variable: str) -> None:
        scheme = "http" if proxy_variable == "HTTP_PROXY" else "https"
        url = f"{scheme}://example.com/"
        with (
            patch.dict(os.environ, {**_without_environment_proxies(), proxy_variable: "http://egress.example:3128"}),
            patch.object(httpx.HTTPTransport, "handle_request", return_value=httpx.Response(200)) as send,
            pinned_client(url, {PUBLIC_IP}) as client,
        ):
            with pytest.raises(SSRFBlockedError, match="proxy"):
                client.get(url, headers={"Authorization": "Bearer fake-test-token"})
            send.assert_not_called()

    @override_settings(SSRF_TRUSTED_PROXY_URLS=["http://egress.example:3128"])
    @pytest.mark.parametrize(
        "scheme,environment,expected_host",
        [
            ("https", {}, "93.184.216.34"),
            ("https", {"HTTPS_PROXY": "http://egress.example:3128"}, "example.com"),
            ("http", {"HTTP_PROXY": "http://egress.example:3128"}, "example.com"),
            ("https", {"ALL_PROXY": "http://egress.example:3128"}, "example.com"),
            ("https", {"HTTPS_PROXY": "http://untrusted.example:3128", "NO_PROXY": "example.com"}, "93.184.216.34"),
            ("https", {"HTTPS_PROXY": "http://untrusted.example:3128", "NO_PROXY": "*"}, "93.184.216.34"),
            ("https", {"HTTPS_PROXY": "http://egress.example:3128", "NO_PROXY": "other.example"}, "example.com"),
        ],
    )
    def test_pins_direct_connections_only(self, scheme: str, environment: dict[str, str], expected_host: str) -> None:
        seen: list[httpx.Request] = []

        def handle_request(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
            seen.append(
                httpx.Request(request.method, request.url, headers=request.headers, extensions=request.extensions)
            )
            return httpx.Response(200)

        with (
            patch.dict(os.environ, {**_without_environment_proxies(), **environment}),
            patch.object(httpx.HTTPTransport, "handle_request", handle_request),
        ):
            url = f"{scheme}://example.com/"
            with pinned_client(url, {PUBLIC_IP}, trust_env=True) as client:
                client.get(url)

        [request] = seen
        assert request.url.host == expected_host

    @override_settings(SSRF_TRUSTED_PROXY_URLS=["http://egress.example:3128"])
    @pytest.mark.parametrize("target", ["https://other.example/", "http://169.254.169.254/"])
    def test_trusted_proxy_refuses_redirect_to_unvalidated_host(self, target: str) -> None:
        with (
            patch.dict(os.environ, {**_without_environment_proxies(), "ALL_PROXY": "http://egress.example:3128"}),
            patch.object(
                httpx.HTTPTransport, "handle_request", return_value=httpx.Response(302, headers={"Location": target})
            ) as send,
            pinned_client("https://example.com/", {PUBLIC_IP}) as client,
        ):
            with pytest.raises(SSRFBlockedError, match="No validated address"):
                client.get("https://example.com/", follow_redirects=True)
            assert send.call_count == 1

    @override_settings(SSRF_TRUSTED_PROXY_URLS=["http://egress.example:3128"])
    @pytest.mark.parametrize("proxy", ["http://egress.example:3129", "http://other.example:3128"])
    def test_explicit_proxy_requires_exact_trust_match(self, proxy: str) -> None:
        with (
            patch.object(httpx.HTTPTransport, "handle_request", return_value=httpx.Response(200)) as send,
            pinned_client("https://example.com/", {PUBLIC_IP}, proxy=proxy, trust_env=False) as client,
        ):
            with pytest.raises(SSRFBlockedError, match="proxy"):
                client.get("https://example.com/")
            send.assert_not_called()

    @override_settings(SSRF_TRUSTED_PROXY_URLS=["http://egress.example:3128"])
    def test_proxy_rejection_does_not_fall_back_to_direct_connection(self) -> None:
        stream = httpcore.MockStream([b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"])
        with (
            patch.dict(os.environ, {**_without_environment_proxies(), "HTTPS_PROXY": "http://egress.example:3128"}),
            patch("httpcore.SyncBackend.connect_tcp", return_value=stream) as connect,
            pinned_client("https://example.com/", {PUBLIC_IP}) as client,
        ):
            with pytest.raises(httpx.ProxyError, match="403"):
                client.get("https://example.com/")
            assert connect.call_count == 1
            assert connect.call_args.kwargs["host"] == "egress.example"

    @override_settings(SSRF_TRUSTED_PROXY_URLS=["http://egress.example:3128"])
    @pytest.mark.parametrize("proxied", [False, True])
    @pytest.mark.parametrize("certificate_rejected", [False, True])
    def test_tls_keeps_original_hostname_and_certificate_verification(
        self, proxied: bool, certificate_rejected: bool
    ) -> None:
        responses = [b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"]
        if proxied:
            responses.insert(0, b"HTTP/1.1 200 Connection Established\r\n\r\n")
        stream = httpcore.MockStream(responses)

        def start_tls(ssl_context: ssl.SSLContext, server_hostname: str, timeout: float) -> httpcore.NetworkStream:
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            assert ssl_context.check_hostname
            assert server_hostname == "example.com"
            if certificate_rejected:
                raise httpcore.ConnectError("CERTIFICATE_VERIFY_FAILED")
            return stream

        environment = {"HTTPS_PROXY": "http://egress.example:3128"} if proxied else {}
        with (
            patch.dict(os.environ, {**_without_environment_proxies(), **environment}),
            patch("httpcore.SyncBackend.connect_tcp", return_value=stream) as connect,
            patch.object(stream, "start_tls", side_effect=start_tls) as tls,
            pinned_client("https://example.com/", {PUBLIC_IP}) as client,
        ):
            if certificate_rejected:
                with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                    client.get("https://example.com/")
            else:
                assert client.get("https://example.com/").status_code == 200
            assert connect.call_args.kwargs["host"] == ("egress.example" if proxied else str(PUBLIC_IP))
            tls.assert_called_once()

    @override_settings(FORCE_URL_VALIDATION=True)
    def test_direct_connection_cannot_rebind_after_validation(self) -> None:
        url = "http://example.com/"
        connection = MagicMock()
        connection.fileno.return_value = -1
        connection.recv.return_value = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"

        def resolve_connection(
            host: str, port: int, *args: object, **kwargs: object
        ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            address = "127.0.0.1" if host == "example.com" else host
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

        with (
            patch("posthog.security.url_validation.resolve_host_ips", return_value={PUBLIC_IP}),
            patch("socket.getaddrinfo", side_effect=resolve_connection),
            patch("socket.socket", return_value=connection),
        ):
            verdict = validate_url_and_pin_ips(url)
            assert verdict.allowed
            with pinned_client(url, verdict.pinned_ips, trust_env=False) as client:
                assert client.get(url).status_code == 200
            connection.connect.assert_called_once_with((str(PUBLIC_IP), 80))
