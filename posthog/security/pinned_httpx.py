"""SSRF-hardened ``httpx`` clients with DNS pinning.

The ``httpx`` counterpart of ``pinned_requests``. Validation resolves the
hostname once, and ``httpx`` resolves it again when it opens the connection, so
a rebinding DNS record can pass validation and still reach an internal address.
``pinned_httpx_client`` closes that window: the client connects to the address
validation accepted, while TLS still verifies the original hostname.

Clients never follow redirects on their own — a redirect target has not been
validated. A caller that follows one must validate the new URL first, and may
reuse the client only while the target stays on the pinned host.
"""

import urllib.parse as urlparse
from types import TracebackType
from typing import Any

import httpx

from posthog.security.pinned_requests import SSRFBlockedError, canonical_pin_host, select_pinned_ip
from posthog.security.url_validation import ResolvedIPs


class PinnedIPTransport(httpx.BaseTransport):
    """Send a request to its pinned IP, over the transport ``httpx`` chose for it.

    Wrapping rather than replacing keeps the routing ``httpx`` builds from the
    environment, so a request that must leave through an egress proxy still
    does, and only the address behind the hostname is fixed.
    """

    def __init__(self, inner: httpx.BaseTransport, pins: dict[str, str]) -> None:
        self._inner = inner
        self._pins = pins

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = canonical_pin_host(request.url.host)
        ip = self._pins.get(host)
        if ip is None:
            # Fail closed: passing the request on would let httpx resolve the host again,
            # and that second resolution is the rebinding window pinning exists to close.
            raise SSRFBlockedError(f"No validated pin for host {host!r}; refusing to connect")

        # ``httpx`` builds the Host header from the original URL and does not rebuild it
        # here, so rewriting the URL changes where we connect and nothing else. The
        # extension carries the original hostname into TLS, for SNI and for certificate
        # verification, which would otherwise run against the IP.
        request.extensions = {**request.extensions, "sni_hostname": host}
        request.url = request.url.copy_with(host=ip)
        return self._inner.handle_request(request)

    def __enter__(self) -> "PinnedIPTransport":
        self._inner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        self._inner.__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        self._inner.close()


def pinned_httpx_client(url: str, pinned_ips: ResolvedIPs, **client_kwargs: Any) -> httpx.Client:
    """Build a client whose connections for ``url``'s host go to a validated IP.

    Pass the IP set from ``validate_url_and_pin_ips``, so the addresses the client
    reaches are the ones the SSRF check accepted. An empty set means pinning was
    skipped on purpose — the dev SSRF bypass, or an operator-configured internal
    URL — and the client is returned as ``httpx`` built it.

    The caller owns the client and must close it.
    """
    client = httpx.Client(**client_kwargs)
    chosen_ip = select_pinned_ip(pinned_ips)
    if chosen_ip is None:
        return client

    pins = {canonical_pin_host(urlparse.urlparse(url).hostname or ""): str(chosen_ip)}
    # ``httpx`` picks a transport per URL: the default one, or a proxy mount when the
    # environment configures a proxy. Wrap every one of them, so no route escapes the
    # pin. These attributes are private but stable (verified against httpx 0.28), and
    # the public API offers no way to wrap the transports httpx builds for itself.
    client._transport = PinnedIPTransport(client._transport, pins)
    client._mounts = {
        pattern: None if transport is None else PinnedIPTransport(transport, pins)
        for pattern, transport in client._mounts.items()
    }
    return client
