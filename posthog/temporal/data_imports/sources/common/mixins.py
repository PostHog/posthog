from collections.abc import Callable, Generator
from contextlib import _GeneratorContextManager, contextmanager
from typing import Any

from posthog.models.integration import Integration

# Re-exported from its leaf module so existing `mixins._is_host_safe`
# importers keep working; `mixins.py` itself still uses it below.
from posthog.temporal.data_imports.host_safety import _is_host_safe

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel

__all__ = ["OAuthMixin", "SSHTunnelMixin", "ValidateDatabaseHostMixin", "_is_host_safe"]


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
