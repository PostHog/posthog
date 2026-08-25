import socket
import ipaddress
import threading
from collections.abc import Callable
from time import monotonic
from typing import Any

import psycopg


def resolve_psycopg_hostaddr_with_timeout(
    host: str,
    port: int,
    timeout: float,
    *,
    fail_on_resolution_error: bool = False,
    abort_check: Callable[[], None] | None = None,
) -> list[str] | None:
    """Resolve a hostname before psycopg's unbounded Python-side DNS lookup."""
    if not host or host.startswith("/"):
        return None

    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass

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
            raise psycopg.OperationalError(f"Timed out resolving database host name after {timeout}s")
        thread.join(min(remaining_seconds, 1.0 if abort_check is not None else remaining_seconds))
    if abort_check is not None:
        abort_check()
    if lookup_error:
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
    return addresses
