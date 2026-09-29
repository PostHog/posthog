"""Bounded HTTP requests to untrusted URLs with DNS pinning."""

import socket
import asyncio
from collections.abc import Mapping
from dataclasses import field
from ipaddress import IPv4Address, IPv6Address
from urllib.parse import urlsplit

import idna
import aiohttp

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, select_pinned_ip
from posthog.security.url_validation import validate_url_and_pin_ips

MAX_RESPONSE_BYTES = 1_048_576


class ResponseLimitExceeded(ValueError):
    pass


@frozen
class PinnedHTTPResult:
    status_code: int
    headers: Mapping[str, str] = field(repr=False)
    content: bytes = field(repr=False)


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


async def pinned_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json: object,
    timeout: float,
    read_body_statuses: tuple[int, ...] = (200,),
) -> PinnedHTTPResult:
    verdict = await asyncio.to_thread(validate_url_and_pin_ips, url)
    if not verdict.allowed:
        raise SSRFBlockedError(verdict.reason)
    pinned_ip = select_pinned_ip(verdict.pinned_ips)
    connector = aiohttp.TCPConnector(
        resolver=PinnedResolver(urlsplit(url).hostname or "", pinned_ip) if pinned_ip else None
    )
    # Bound headers and body together so a slow endpoint cannot hold a worker indefinitely.
    client_timeout = aiohttp.ClientTimeout(total=timeout, ceil_threshold=timeout + 1)
    # nosemgrep: aiohttp-missing-trust-env -- A proxy would resolve the host outside its validated DNS pin.
    async with aiohttp.ClientSession(
        connector=connector, timeout=client_timeout, auto_decompress=False, trust_env=False
    ) as session:
        response = await session.request(
            method, url, headers={**headers, "Accept-Encoding": "identity"}, json=json, allow_redirects=False
        )
        async with response:
            content = bytearray()
            if response.status in read_body_statuses:
                length = response.content_length
                if (length is not None and length > MAX_RESPONSE_BYTES) or response.headers.get(
                    "Content-Encoding", "identity"
                ).lower() != "identity":
                    raise ResponseLimitExceeded("Endpoint response exceeded its limits")
                async for chunk in response.content.iter_chunked(8192):
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ResponseLimitExceeded("Endpoint response exceeded its limits")
                    content.extend(chunk)
            return PinnedHTTPResult(status_code=response.status, headers=response.headers, content=bytes(content))
