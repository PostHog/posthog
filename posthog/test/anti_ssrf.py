from collections.abc import Iterable
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import TYPE_CHECKING

from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from unittest.mock import _patch

PUBLIC_TEST_IP = ip_address("93.184.216.34")


def mock_anti_ssrf_dns_lookup(
    resolves_to: Iterable[str | IPv4Address | IPv6Address] = (PUBLIC_TEST_IP,),
) -> "_patch[MagicMock]":
    """Replace only the DNS lookup of the anti-SSRF guard in `posthog.security.url_validation`.

    The guard still runs in full: it parses the URL, checks the host, and rejects an internal address.
    Only the answer to "which addresses does this host name resolve to" comes from the test,
    so the test does not depend on real DNS and stays in control of what the guard sees.
    The default is a public address, which lets a URL through the guard.
    Pass an internal address to check that the guard blocks it, or an empty list for a host name that does not resolve.

    Use it as a class decorator, a method decorator or a context manager.
    As a decorator it passes the mock to the test method as an extra argument, like `unittest.mock.patch`.
    """
    return patch(
        "posthog.security.url_validation.resolve_host_ips",
        return_value={ip_address(ip) for ip in resolves_to},
    )
