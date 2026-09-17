"""SSRF-hardened httpx clients with DNS pinning.

The ``requests`` counterpart is ``pinned_requests``. This module is for callers on ``httpx``,
which resolves the host again when it opens the connection. A URL that passed validation can
therefore still reach an internal address if its DNS record changes in between.

``pinned_client`` returns an ``httpx.Client`` whose direct connections go to the validated
address of the URL's host. The ``Host`` header and the TLS server name keep the host name, so
the upstream server sees an ordinary request and the certificate check stays on the name.

A connection through an environment proxy (``HTTPS_PROXY``) is not pinned. The proxy resolves
the name itself, and the CONNECT tunnel in httpcore uses the connect target as the TLS server
name, so a pinned address there would fail certificate verification.

Redirects are never followed automatically. A same-host redirect reuses the pin. Any other
host is refused, because it was not validated.
"""

import ipaddress
from collections.abc import Mapping
from typing import Any

import httpx

from posthog.security.pinned_requests import SSRFBlockedError, select_pinned_ip
from posthog.security.url_validation import ResolvedIPs

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _pin_key(url: httpx.URL) -> str:
    """The host form httpx connects to: lowercase punycode without the DNS root dot."""
    return url.raw_host.decode("ascii").rstrip(".")


class PinnedTransport(httpx.BaseTransport):
    """Sends each request for a pinned host to the validated address.

    Once anything is pinned, a request for another host is refused instead of falling back
    to a fresh DNS lookup, because that lookup is the rebinding window pinning closes. An
    empty pin map passes every request through, for the dev bypass and for endpoints that
    are reached by name inside the cluster.
    """

    def __init__(self, inner: httpx.BaseTransport, pins: Mapping[str, IPAddress]) -> None:
        self._inner = inner
        self._pins = dict(pins)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = _pin_key(request.url)
        ip = self._pins.get(host)
        if ip is None:
            if self._pins:
                raise SSRFBlockedError(f"No validated address for host {host!r}; refusing to connect")
            return self._inner.handle_request(request)

        # The Host header was filled from the original URL when the request was built, and
        # replacing the URL afterwards leaves it as it is.
        request.url = request.url.copy_with(host=str(ip))
        if request.url.scheme == "https":
            request.extensions["sni_hostname"] = host
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class PinnedClient(httpx.Client):
    """An ``httpx.Client`` whose direct connections go to validated addresses.

    Only the default transport is wrapped. httpx builds the proxy transports separately and
    routes each request by its original URL, so ``HTTPS_PROXY`` and ``NO_PROXY`` keep their
    meaning and a proxied request still carries the host name. Passing ``transport=`` to
    ``httpx.Client`` would instead switch environment proxies off altogether.
    """

    def __init__(self, *, pins: Mapping[str, IPAddress], **kwargs: Any) -> None:
        self._pins = dict(pins)
        super().__init__(**kwargs)

    def _init_transport(self, *args: Any, **kwargs: Any) -> httpx.BaseTransport:
        return PinnedTransport(super()._init_transport(*args, **kwargs), self._pins)


def pinned_client(url: str, pinned_ips: ResolvedIPs, **kwargs: Any) -> httpx.Client:
    """An httpx client for ``url`` that connects to one of its validated addresses.

    ``pinned_ips`` is the set ``validate_url_and_pin_ips`` returned for ``url``. An empty set
    pins nothing, which is what the validator returns under the dev bypass.
    """
    pins: dict[str, IPAddress] = {}
    ip = select_pinned_ip(pinned_ips)
    if ip is not None:
        pins[_pin_key(httpx.URL(url))] = ip
    return PinnedClient(pins=pins, **kwargs)
