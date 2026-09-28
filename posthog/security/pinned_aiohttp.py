"""Resolve an aiohttp request to an already-validated address."""

import socket
from ipaddress import IPv4Address, IPv6Address

import idna
import aiohttp

from posthog.security.pinned_requests import SSRFBlockedError


class PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, hostname: str, ip: IPv4Address | IPv6Address) -> None:
        self.hostname = idna.encode(hostname.rstrip("."), uts46=True).decode("ascii").lower()
        self.ip = ip

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[aiohttp.abc.ResolveResult]:
        if idna.encode(host.rstrip("."), uts46=True).decode("ascii").lower() != self.hostname:
            raise SSRFBlockedError("The endpoint resolved to an unvalidated host")
        return [
            {
                "hostname": host,
                "host": str(self.ip),
                "port": port,
                "family": socket.AF_INET if self.ip.version == 4 else socket.AF_INET6,
                "proto": 0,
                "flags": 0,
            }
        ]

    async def close(self) -> None:
        pass
