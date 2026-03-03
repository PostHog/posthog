import socket
from collections.abc import Callable, Generator
from contextlib import _GeneratorContextManager, contextmanager
from typing import Any

from posthog.cloud_utils import is_cloud
from posthog.models.integration import Integration
from posthog.utils import get_instance_region

from products.data_warehouse.backend.models.ssh_tunnel import SSHTunnel
from products.data_warehouse.backend.models.util import _is_safe_public_ip


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
    if not is_cloud():
        return True, None

    region = get_instance_region()
    if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
        return True, None

    normalized = host.lower().strip().rstrip(".")
    if normalized in {"localhost"}:
        return False, "Hosts with internal IP addresses are not allowed"

    try:
        if not _is_safe_public_ip(host):
            return False, "Hosts with internal IP addresses are not allowed"
    except ValueError:
        pass

    try:
        addrinfo = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in addrinfo:
            resolved_ip = sockaddr[0]
            if not _is_safe_public_ip(str(resolved_ip)):
                return False, "Hosts with internal IP addresses are not allowed"
    except socket.gaierror:
        return False, "Host could not be resolved"

    return True, None


class SSHTunnelMixin:
    """Mixin for sources that support SSH tunnels"""

    @contextmanager
    def with_ssh_tunnel(self, config) -> Generator[tuple[str, int], Any, None]:
        if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
            ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

            with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
                if tunnel is None:
                    raise Exception("Can't open tunnel to SSH server")

                yield tunnel.local_bind_host, tunnel.local_bind_port
        else:
            yield config.host, config.port

    def make_ssh_tunnel_func(self, config) -> Callable[[], _GeneratorContextManager[tuple[str, int]]]:
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
