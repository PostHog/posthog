"""SSRF host-safety checks for data-warehouse / data-import HTTP traffic.

This module is deliberately a *leaf*: it imports only the stdlib and a
couple of lightweight `posthog` core helpers. It pulls in no Django models
and no product code, so it is safe to import from low-level transport code
(`sources/common/http/transport.py`) without dragging the ORM into the
HTTP stack, and equally safe to import from product model code.

`_is_host_safe` used to live in `sources/common/mixins.py` and
`_is_safe_public_ip` in `products/data_warehouse/backend/models/util.py`;
both are re-exported from their old homes for backwards compatibility.
"""

import socket
from ipaddress import IPv6Address, ip_address

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region


def _is_safe_public_ip(host: str) -> bool:
    ip = ip_address(host)

    # IPv6 can carry embedded IPv4 addresses that need the same SSRF checks.
    if isinstance(ip, IPv6Address):
        if ip.ipv4_mapped:
            return _is_safe_public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour:
            return _is_safe_public_ip(str(ip.sixtofour))

    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _is_host_safe(
    host: str,
    team_id: int | None,
    *,
    resolve: bool = True,
    resolved_ip: str | None = None,
) -> tuple[bool, str | None]:
    """Validate that a host is not an internal/private IP address.

    Only enforced on cloud deployments — self-hosted instances are allowed
    to connect to any host.

    Hostname-based exemptions (`.postwh.com`, `localhost`) and the team
    allowlist are always evaluated against `host`. The IP-safety check then
    runs in one of three modes:

    - `resolved_ip` given: vet that exact address and skip DNS entirely. The
      post-connect SSRF check passes the IP the socket genuinely connected
      to, so a rebinding resolver cannot shift the target after the fact.
    - `resolve=True` (default), no `resolved_ip`: resolve `host` via DNS and
      vet every resolved IP — the full check.
    - `resolve=False`, no `resolved_ip`: skip IP resolution — only the
      hostname exemptions and a literal-IP check on `host` run. A cheap
      pre-flight that does no network I/O.

    team whitelist: team_id 2 in US, team_id 1 in EU are allowed
    to use internal IPs. A team_id of None has no allowlist entry, so the
    full check always applies.
    """
    if not is_cloud():
        return True, None

    region = get_instance_region()
    if region == "E2E":
        return True, None

    if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
        return True, None

    normalized = host.lower().strip().rstrip(".")

    # PostHog-managed DuckLake hosts resolve to internal IPs but are safe.
    if normalized.endswith(".postwh.com"):
        return True, None

    if normalized in {"localhost"}:
        return False, "Hosts with internal IP addresses are not allowed"

    if resolved_ip is not None:
        if not _is_safe_public_ip(resolved_ip):
            return False, "Hosts with internal IP addresses are not allowed"
        return True, None

    try:
        if not _is_safe_public_ip(host):
            return False, "Hosts with internal IP addresses are not allowed"
    except ValueError:
        # `host` isn't a canonical IP literal. It may still be an obfuscated
        # IPv4 literal — decimal (2130706433), hex (0x7f000001) or short-form
        # (127.1) — that `inet_aton` accepts. Canonicalize and re-check so the
        # cheap no-DNS pre-flight isn't bypassed by an obfuscated internal IP.
        try:
            canonical = socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            canonical = None
        if canonical is not None and not _is_safe_public_ip(canonical):
            return False, "Hosts with internal IP addresses are not allowed"

    if not resolve:
        return True, None

    try:
        addrinfo = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in addrinfo:
            resolved = sockaddr[0]
            if not _is_safe_public_ip(str(resolved)):
                return False, "Hosts with internal IP addresses are not allowed"
    except socket.gaierror:
        return False, "Host could not be resolved"

    return True, None
