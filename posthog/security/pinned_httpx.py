"""SSRF-hardened httpx clients with DNS pinning.

The ``requests`` counterpart is ``pinned_requests``. This module is for callers on ``httpx``,
which resolves the host again when it opens the connection. A URL that passed validation can
therefore still reach an internal address if its DNS record changes in between.

``pinned_client`` returns an ``httpx.Client`` whose direct connections go to the validated
address of the URL's host. The ``Host`` header and the TLS server name keep the host name, so
the upstream server sees an ordinary request and the certificate check stays on the name.

A proxy must appear in ``SSRF_TRUSTED_PROXY_URLS`` before it can receive a request.
Operators must verify that each trusted proxy blocks sensitive destination addresses after
DNS resolution. An environment proxy variable alone does not establish this trust.
A connection through a trusted proxy is not pinned. The proxy resolves
the name itself, and the CONNECT tunnel in httpcore uses the connect target as the TLS server
name, so a pinned address there would fail certificate verification.

Redirects are never followed automatically. A same-host redirect reuses the pin. Any other
host is refused, because it was not validated.
"""

import ipaddress
from collections.abc import Mapping
from typing import Any

from django.conf import settings

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
    empty pin map skips the host restriction for the dev bypass and internal endpoints.
    Proxy trust checks still apply when no address is pinned.
    """

    def __init__(
        self, inner: httpx.BaseTransport, pins: Mapping[str, IPAddress], *, proxy_url: httpx.URL | None = None
    ) -> None:
        self._inner = inner
        self._pins = dict(pins)
        self._proxy_url = proxy_url
        self._trusted_proxy = proxy_url is None or proxy_url in {
            httpx.URL(url) for url in settings.SSRF_TRUSTED_PROXY_URLS
        }

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = _pin_key(request.url)
        ip = self._pins.get(host)
        if self._pins and ip is None:
            raise SSRFBlockedError(f"No validated address for host {host!r}; refusing to connect")
        if not self._trusted_proxy:
            raise SSRFBlockedError(
                "Outbound proxy is not trusted. Ask an administrator to configure SSRF_TRUSTED_PROXY_URLS."
            )
        if self._proxy_url is not None or ip is None:
            return self._inner.handle_request(request)

        # The Host header was filled from the original URL when the request was built, and
        # replacing the URL afterwards leaves it as it is.
        original_url = request.url
        try:
            request.url = original_url.copy_with(host=str(ip))
            if request.url.scheme == "https":
                request.extensions["sni_hostname"] = host
            return self._inner.handle_request(request)
        finally:
            request.url = original_url

    def close(self) -> None:
        self._inner.close()


class PinnedClient(httpx.Client):
    """An ``httpx.Client`` whose direct connections go to validated addresses.

    httpx routes each request by its original URL, so ``HTTPS_PROXY`` and ``NO_PROXY`` keep
    their meaning. Both direct and proxy transports enforce the host restriction. Trusted
    proxies receive the host name; other proxies fail closed. Passing ``transport=`` to
    ``httpx.Client`` would instead switch environment proxies off altogether.
    """

    def __init__(self, *, pins: Mapping[str, IPAddress], **kwargs: Any) -> None:
        self._pins = dict(pins)
        super().__init__(**kwargs)

    def _init_transport(self, *args: Any, **kwargs: Any) -> httpx.BaseTransport:
        return PinnedTransport(super()._init_transport(*args, **kwargs), self._pins)

    def _init_proxy_transport(self, proxy: httpx.Proxy, *args: Any, **kwargs: Any) -> httpx.BaseTransport:
        return PinnedTransport(super()._init_proxy_transport(proxy, *args, **kwargs), self._pins, proxy_url=proxy.url)


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
