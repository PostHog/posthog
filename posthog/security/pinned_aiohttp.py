import socket
import ipaddress
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from typing import Any, Literal

from django.conf import settings

from aiohttp import ClientRequest, ClientSession, ClientTimeout, TCPConnector
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.connector import Connection
from aiohttp.tracing import Trace
from yarl import URL

from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import ResolvedIPs, canonicalize_host


def _get_family_from_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> Literal[socket.AddressFamily.AF_INET] | Literal[socket.AddressFamily.AF_INET6]:
    return socket.AF_INET if ip.version == 4 else socket.AF_INET6


def _make_filter_ip_family(
    family: socket.AddressFamily,
) -> Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool]:
    def _filter(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if family not in (socket.AF_UNSPEC, _get_family_from_ip(ip)):
            return False
        return True

    return _filter


class PinnedResolver(AbstractResolver):
    """DNS resolver pinned to pre-resolved ips for hosts.

    After IPs are validated, this re-uses the hosts mapped to the validated IPs
    instead of resolving DNS.
    """

    def __init__(self, host_to_resolved_ips: Mapping[str, ResolvedIPs]) -> None:
        self._pinned = host_to_resolved_ips

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        """Return pinned ips for host, if any.

        Raises:
            SSRFBlockedError: When there are no pinned ips for the host.
        """
        ips = self._pinned.get(canonicalize_host(host))
        if not ips:
            raise SSRFBlockedError(f"Unknown host: {host}")

        _filter_ip_family = _make_filter_ip_family(family=family)

        return [
            ResolveResult(
                hostname=host,
                host=str(ip),
                port=port,
                family=_get_family_from_ip(ip),
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST,
            )
            for ip in filter(_filter_ip_family, ips)
        ]

    async def close(self) -> None:
        pass


class PinnedTCPConnector(TCPConnector):
    def __init__(self, host_to_resolved_ips: Mapping[str, ResolvedIPs], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._host_to_resolved_ips = host_to_resolved_ips
        self._pinned_resolver = PinnedResolver(host_to_resolved_ips)
        self._trusted_proxies = frozenset(URL(url) for url in settings.SSRF_TRUSTED_PROXY_URLS)
        self._using_proxy: ContextVar[bool] = ContextVar("pinned_aiohttp_using_proxy", default=False)

    async def connect(self, req: ClientRequest, traces: list[Trace], timeout: ClientTimeout) -> Connection:
        host = req.url.raw_host
        assert host is not None
        if self._host_to_resolved_ips and not self._host_to_resolved_ips.get(canonicalize_host(host)):
            raise SSRFBlockedError(f"Unknown host: {host}")

        if req.proxy is not None and req.proxy not in self._trusted_proxies:
            raise SSRFBlockedError(
                "Outbound proxy is not trusted. Ask an administrator to configure SSRF_TRUSTED_PROXY_URLS."
            )

        # Proxied requests bypass pins, contextvar keeps things local to this
        # task so other concurrent connection attempts don't read this.
        token = self._using_proxy.set(req.proxy is not None)
        try:
            return await super().connect(req, traces, timeout)
        finally:
            self._using_proxy.reset(token)

    async def _resolve_host(self, host: str, port: int, traces: Sequence[Trace] | None = None) -> list[ResolveResult]:
        if self._using_proxy.get() or not self._host_to_resolved_ips:
            return await super()._resolve_host(host, port, traces)
        return await self._pinned_resolver.resolve(host, port, socket.AddressFamily(self.family))


def pinned_session(host_to_resolved_ips: Mapping[str, ResolvedIPs], **kwargs: Any) -> ClientSession:
    connector = PinnedTCPConnector(host_to_resolved_ips)
    return ClientSession(connector=connector, trust_env=True, **kwargs)
