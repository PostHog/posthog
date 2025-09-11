from collections.abc import Callable, Generator
from contextlib import _GeneratorContextManager, contextmanager
from typing import Any

from posthog.cloud_utils import is_cloud
from posthog.models.integration import Integration
from posthog.utils import get_instance_region
from posthog.warehouse.models.ssh_tunnel import SSHTunnel


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
                with ssh_tunnel.get_tunnel(config.host, config.port) as t:
                    if t is None:
                        raise Exception("Can't open tunnel to SSH server")
                    yield t.local_bind_host, t.local_bind_port

            return with_ssh_func

        @contextmanager
        def without_ssh_func():
            yield config.host, config.port

        return without_ssh_func

    def ssh_tunnel_is_valid(self, config) -> tuple[bool, str | None]:
        if hasattr(config, "ssh_tunnel") and config.ssh_tunnel and config.ssh_tunnel.enabled:
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

    def is_database_host_valid(self, host: str, team_id: int, using_ssh_tunnel: bool) -> tuple[bool, str | None]:
        if using_ssh_tunnel:
            return True, None

        if host.startswith("172") or host.startswith("10") or host.startswith("localhost"):
            if is_cloud():
                region = get_instance_region()
                if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
                    return True, None
                else:
                    return False, "Hosts with internal IP addresses are not allowed"

        return True, None
