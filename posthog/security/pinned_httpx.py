"""SSRF-hardened httpx transports with DNS pinning.

The httpx counterpart to ``pinned_requests``, for callers that don't get to pick
their HTTP library: vendor SDKs (OpenAI, Anthropic) take an ``httpx.Client`` and
expose no hook between DNS resolution and connect, so a transport that dials the
address already validated is the only place to close the rebinding window.

``pinned_transport`` validates the URL and returns a transport that rewrites each
request's host to the validated IP while keeping the original hostname for the
``Host`` header and for TLS SNI, so certificate verification still runs against
the hostname the user configured.

Build the client with ``follow_redirects=False``. A redirect target has not been
validated, and following one inside the client would leave the pin behind —
callers that need to follow a redirect must re-enter this helper with the new URL.
"""

import ipaddress
import urllib.parse as urlparse
from typing import Any

import httpx

from posthog.security.pinned_requests import SSRFBlockedError, canonical_host, select_pinned_ip
from posthog.security.url_validation import validate_url_and_pin_ips


class PinnedIPHTTPTransport(httpx.HTTPTransport):
    """httpx transport that connects only to pre-validated IPs.

    Pin every host before the client issues a request — ``handle_request`` only
    reads the map.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pin_map: dict[str, str] = {}

    def pin(self, hostname: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        self._pin_map[canonical_host(hostname)] = str(ip)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = canonical_host((request.url.raw_host or b"").decode("ascii"))
        ip_str = self._pin_map.get(host)

        if ip_str is None:
            # Fail closed, same rule as PinnedIPAdapter: a transport that pinned at least one
            # host must refuse a request it can't match rather than let httpx re-resolve DNS —
            # that re-resolution is the rebinding window pinning exists to close. An empty map
            # means pinning was intentionally skipped (the dev SSRF bypass), so pass through.
            if self._pin_map:
                raise SSRFBlockedError(f"No validated pin for host {host!r}; refusing to connect")
            return super().handle_request(request)

        # Captured before the rewrite, so the request still carries the authority the caller
        # asked for. `sni_hostname` is what httpcore hands the SSL context as `server_hostname`,
        # which drives both SNI and certificate verification — without it TLS would be checked
        # against the IP and every pinned https request would fail.
        request.headers["Host"] = request.url.netloc.decode("ascii")
        request.extensions = {**request.extensions, "sni_hostname": host}
        request.url = request.url.copy_with(host=ip_str)

        return super().handle_request(request)


def pinned_transport(url: str, **kwargs: Any) -> PinnedIPHTTPTransport:
    """Return a transport pinned to ``url``'s validated IPs.

    Raises ``SSRFBlockedError`` when the URL fails validation, before any
    connection is opened. Mount on a client built with ``follow_redirects=False``.
    """
    allowed, reason, pinned_ips = validate_url_and_pin_ips(url)
    if not allowed:
        raise SSRFBlockedError(reason or "URL blocked by SSRF protection")

    transport = PinnedIPHTTPTransport(**kwargs)
    chosen_ip = select_pinned_ip(pinned_ips)
    if chosen_ip is not None:
        transport.pin(urlparse.urlparse(url).hostname or "", chosen_ip)
    return transport
