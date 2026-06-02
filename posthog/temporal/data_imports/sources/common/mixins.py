import socket
import asyncio
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import _GeneratorContextManager, asynccontextmanager, contextmanager
from typing import Any

import structlog

from posthog.cloud_utils import is_cloud
from posthog.models.integration import Integration
from posthog.utils import get_instance_region

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel, SSHTunnelConfig
from products.warehouse_sources.backend.models.util import _is_safe_public_ip

logger = structlog.get_logger(__name__)

_INTERNAL_IP_ERROR = "Hosts with internal IP addresses are not allowed"
_DNS_FAILURE_ERROR = "Host could not be resolved"


def _is_host_safe(host: str, team_id: int) -> tuple[bool, str | None]:
    """Validate that a host is not an internal/private IP address.

    Only enforced on cloud deployments — self-hosted instances are allowed
    to connect to any host.

    Resolves hostnames via DNS and checks all resolved IPs against
    _is_safe_public_ip to block private, loopback, link-local, multicast,
    reserved, and IPv6-mapped internal addresses.

    team whitelist: team_id 2 in US, team_id 1 in EU are allowed
    to use internal IPs.
    """

    def _log(decision: str, stage: str, reason: str | None, resolved_ips: list[str] | None = None) -> None:
        if decision == "block":
            log_fn = logger.warning  # SSRF attempt — always logged
        elif stage in ("not_cloud", "e2e"):
            log_fn = logger.debug  # never fires on cloud / spammy on self-hosted
        else:
            log_fn = logger.info

        log_fn(
            "data_imports.host_check",
            host=host,
            team_id=team_id,
            decision=decision,
            stage=stage,
            reason=reason,
            resolved_ips=resolved_ips,
        )

    if not is_cloud():
        _log("allow", "not_cloud", None)
        return True, None

    region = get_instance_region()
    if region == "E2E":
        _log("allow", "e2e", None)
        return True, None

    if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
        _log("allow", "team_allowlist", None)
        return True, None

    normalized = host.lower().strip().rstrip(".")

    # PostHog-managed DuckLake hosts resolve to internal IPs but are safe.
    if normalized.endswith(".postwh.com"):
        _log("allow", "postwh_managed", None)
        return True, None

    if normalized in {"localhost"}:
        _log("block", "localhost", _INTERNAL_IP_ERROR)
        return False, _INTERNAL_IP_ERROR

    try:
        if not _is_safe_public_ip(host):
            _log("block", "literal_ip", _INTERNAL_IP_ERROR)
            return False, _INTERNAL_IP_ERROR
    except ValueError:
        pass

    try:
        addrinfo = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        resolved_ips = [str(sockaddr[0]) for *_meta, sockaddr in addrinfo]
        for resolved_ip in resolved_ips:
            if not _is_safe_public_ip(resolved_ip):
                _log("block", "resolved_ip", _INTERNAL_IP_ERROR, resolved_ips)
                return False, _INTERNAL_IP_ERROR
    except socket.gaierror:
        _log("block", "dns_failure", _DNS_FAILURE_ERROR)
        return False, _DNS_FAILURE_ERROR

    _log("allow", "resolved_ip", None, resolved_ips)
    return True, None


@contextmanager
def open_ssh_tunnel(config) -> Generator[tuple[str, int], Any, None]:
    """Yield `(host, port)` for a database connection, going through an SSH tunnel if configured."""
    if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

        with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
            if tunnel is None:
                raise Exception("Can't open tunnel to SSH server")

            yield tunnel.local_bind_host, tunnel.local_bind_port
    else:
        yield config.host, config.port


def make_ssh_tunnel_factory(config) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
    """Return a zero-arg factory that opens a fresh `open_ssh_tunnel(config)` context each call.

    The dlt pipeline factories accept a tunnel-factory callable so the tunnel can be
    (re)opened inside the pipeline process.
    """
    if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

        @contextmanager
        def with_ssh_func():
            with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
                if tunnel is None:
                    raise Exception("Can't open tunnel to SSH server")
                yield tunnel.local_bind_host, tunnel.local_bind_port

        return with_ssh_func

    @contextmanager
    def without_ssh_func():
        yield config.host, config.port

    return without_ssh_func


def ssh_tunnel_config_is_valid(ssh_tunnel_config: dict[str, Any] | None, team_id: int) -> tuple[bool, str | None]:
    """Validate a raw SSH tunnel config dict (as stored on a batch export destination).

    Mirrors `SSHTunnelMixin.ssh_tunnel_is_valid` but accepts the plain dict that batch
    exports carry through their workflow inputs instead of a typed `Config` object.
    Returns `(True, None)` when no tunnel is configured or it is disabled.
    """
    if not ssh_tunnel_config:
        return True, None

    config = SSHTunnelConfig.from_dict(ssh_tunnel_config)
    if not config.enabled:
        return True, None

    if not config.host:
        return False, "SSH tunnel host is required"

    if not config.port:
        return False, "SSH tunnel port is required"

    is_host_valid, host_errors = _is_host_safe(config.host, team_id)
    if not is_host_valid:
        return False, f"SSH tunnel host not allowed: {host_errors}"

    ssh_tunnel = SSHTunnel.from_config(config)

    is_auth_valid, auth_errors = ssh_tunnel.is_auth_valid()
    if not is_auth_valid:
        return False, auth_errors

    is_port_valid, port_errors = ssh_tunnel.has_valid_port()
    if not is_port_valid:
        return False, port_errors

    return True, None


def ssh_tunnel_requires_tls(ssh_tunnel_config: dict[str, Any] | None) -> bool:
    """Whether the database connection behind this tunnel should still require TLS.

    Databases reachable only through a bastion often don't terminate TLS themselves, so
    the tunnel form exposes a `require_tls` toggle. Returns `True` (require TLS) when no
    tunnel is configured, the tunnel is disabled, or the toggle is left on.
    """
    if not ssh_tunnel_config:
        return True

    config = SSHTunnelConfig.from_dict(ssh_tunnel_config)
    if not config.enabled:
        return True

    return config.require_tls.enabled


@asynccontextmanager
async def aopen_ssh_tunnel_for_config(
    ssh_tunnel_config: dict[str, Any] | None, host: str, port: int
) -> AsyncIterator[tuple[str, int]]:
    """Async variant of `open_ssh_tunnel` taking a raw config dict.

    Yields the `(host, port)` to connect to: the tunnel's local bind address when a tunnel
    is configured and enabled, otherwise the original `(host, port)`. The blocking tunnel
    start/stop run in a thread so they don't block the activity's event loop.
    """
    if not ssh_tunnel_config:
        yield host, port
        return

    config = SSHTunnelConfig.from_dict(ssh_tunnel_config)
    if not config.enabled:
        yield host, port
        return

    ssh_tunnel = SSHTunnel.from_config(config)
    forwarder = ssh_tunnel.get_tunnel(host, port)
    await asyncio.to_thread(forwarder.start)
    try:
        yield forwarder.local_bind_host, forwarder.local_bind_port
    finally:
        await asyncio.to_thread(forwarder.stop)


class SSHTunnelMixin:
    """Mixin for sources that support SSH tunnels"""

    def with_ssh_tunnel(self, config) -> _GeneratorContextManager[tuple[str, int]]:
        return open_ssh_tunnel(config)

    def make_ssh_tunnel_func(self, config) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
        return make_ssh_tunnel_factory(config)

    def ssh_tunnel_is_valid(self, config, team_id: int) -> tuple[bool, str | None]:
        if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
            if config.ssh_tunnel.host:
                is_host_valid, host_errors = _is_host_safe(config.ssh_tunnel.host, team_id)
                if not is_host_valid:
                    return False, f"SSH tunnel host not allowed: {host_errors}"

            ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)
            is_auth_valid, auth_errors = ssh_tunnel.is_auth_valid()
            if not is_auth_valid:
                return is_auth_valid, auth_errors

            is_port_valid, port_errors = ssh_tunnel.has_valid_port()
            if not is_port_valid:
                return is_port_valid, port_errors

        return True, None


class OAuthMixin:
    """Mixin for OAuth-based sources"""

    def get_oauth_integration(self, integration_id: int, team_id: int) -> Integration:
        """Get OAuth integration from integration ID"""
        if not integration_id:
            raise ValueError(f"Missing integration ID")

        if not Integration.objects.filter(id=integration_id, team_id=team_id).exists():
            raise ValueError(f"Integration not found: {integration_id}")

        return Integration.objects.get(id=integration_id, team_id=team_id)


class ValidateDatabaseHostMixin:
    """Mixin for database-based sources to validate connection host"""

    def is_database_host_valid(
        self, host: str, team_id: int, using_ssh_tunnel: bool = False
    ) -> tuple[bool, str | None]:
        if using_ssh_tunnel:
            return True, None

        return _is_host_safe(host, team_id)
