import socket
import ipaddress
import threading
from collections.abc import Callable
from functools import lru_cache
from time import monotonic
from typing import Any

import psycopg

# A public address that is only ever connected to on a connectionless socket, so no packet is sent.
# Any global unicast v6 address would do — this one is a root nameserver.
_IPV6_ROUTE_PROBE_ADDRESS = "2001:500:2f::f"


@lru_cache(maxsize=1)
def has_ipv6_route() -> bool:
    """Whether this host can route to the public IPv6 internet.

    A UDP `connect` picks a source address from the routing table without sending anything, so this
    costs a syscall and no network round trip. Cached: a pod's routing table does not change under
    it, and this sits in front of every outbound database connection.
    """
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
            probe.connect((_IPV6_ROUTE_PROBE_ADDRESS, 53))
        return True
    except OSError:
        return False


def prefer_routable_addresses(addresses: list[str]) -> list[str]:
    """Drop addresses in a family this host cannot route to, unless that would leave nothing.

    A dual-stack hostname resolves IPv6-first by RFC 6724, so on an IPv4-only host every v6 address
    fails with ENETUNREACH. Keeping them costs more than latency: psycopg reports only the LAST
    attempt's error, so a trailing unroutable address masks the real, actionable error raised by an
    address that did reach the server — and a caller that decides what to do next by reading that
    message (see the libpq `options` fallback in the postgres source) then decides on the wrong one.

    A v6-only host keeps its addresses: unroutable beats nothing to connect to.
    """
    if has_ipv6_route():
        return addresses

    def _is_ipv6(address: str) -> bool:
        try:
            return ipaddress.ip_address(address.strip("[]")).version == 6
        except ValueError:
            return False

    routable = [a for a in addresses if not _is_ipv6(a)]
    return routable or addresses


# The resolver answers with one of these when the lookup itself failed, rather than reaching a
# verdict on the name: the resolver was unreachable or timed out (EAI_AGAIN), or the lookup could
# not complete locally (EAI_SYSTEM, EAI_MEMORY). A caller that refuses the host on one of these
# blames the customer for a failure on our side, so they stay retryable. Every other code is an
# answer about the name itself.
_TEMPORARY_RESOLUTION_ERRNOS = frozenset({socket.EAI_AGAIN, socket.EAI_SYSTEM, socket.EAI_MEMORY})


def is_temporary_resolution_failure(error: BaseException) -> bool:
    """Whether a failed lookup is the resolver failing, rather than an answer about the name."""
    return isinstance(error, socket.gaierror) and error.errno in _TEMPORARY_RESOLUTION_ERRNOS


# The bounded lookup's own transient failures. A classifier that matches on the message reuses
# these strings, so a reword here cannot silently drop the classification.
HOST_RESOLUTION_TIMEOUT_ERROR = "Timed out resolving database host name"
TEMPORARY_HOST_RESOLUTION_ERROR = "Temporary failure resolving database host name"


def is_resolvable_hostname(host: str) -> bool:
    """Whether `host` is a name a resolver would look up: not empty, not a Unix socket path, not an IP literal."""
    if not host or host.startswith("/"):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True
    return False


def resolve_psycopg_hostaddr_with_timeout(
    host: str,
    port: int,
    timeout: float,
    *,
    fail_on_resolution_error: bool = False,
    abort_check: Callable[[], None] | None = None,
    raise_on_temporary_failure: bool = False,
) -> list[str] | None:
    """Resolve a hostname before psycopg's unbounded Python-side DNS lookup.

    `raise_on_temporary_failure` turns a resolver failure that is not an answer about the name
    (see `is_temporary_resolution_failure`) into a retryable `psycopg.OperationalError` instead of
    `None`, for callers that treat `None` as a name that does not exist.
    """
    if not is_resolvable_hostname(host):
        return None

    addrinfo: list[Any] = []
    lookup_error: list[BaseException] = []

    def _lookup() -> None:
        try:
            addrinfo.extend(socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP, type=socket.SOCK_STREAM))
        except BaseException as error:  # noqa: BLE001 — re-raised on the calling thread below
            lookup_error.append(error)

    # A daemon lets the caller abandon a stalled OS resolver without pinning the query worker.
    thread = threading.Thread(target=_lookup, daemon=True)
    thread.start()
    deadline = monotonic() + timeout
    while thread.is_alive():
        if abort_check is not None:
            abort_check()
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise psycopg.OperationalError(f"{HOST_RESOLUTION_TIMEOUT_ERROR} after {timeout}s")
        thread.join(min(remaining_seconds, 1.0 if abort_check is not None else remaining_seconds))
    if abort_check is not None:
        abort_check()
    if lookup_error:
        if raise_on_temporary_failure and is_temporary_resolution_failure(lookup_error[0]):
            raise psycopg.OperationalError(TEMPORARY_HOST_RESOLUTION_ERROR) from lookup_error[0]
        if isinstance(lookup_error[0], OSError):
            if fail_on_resolution_error:
                raise psycopg.OperationalError("Could not resolve database host name") from lookup_error[0]
            return None
        raise lookup_error[0]
    if not addrinfo:
        if fail_on_resolution_error:
            raise psycopg.OperationalError("Could not resolve database host name")
        return None

    seen: set[str] = set()
    addresses: list[str] = []
    for info in addrinfo:
        address = str(info[4][0])
        if address not in seen:
            seen.add(address)
            addresses.append(address)
    return prefer_routable_addresses(addresses)
