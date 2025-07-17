from contextlib import contextmanager
from typing import Any
from collections.abc import Generator
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.models.integration import Integration


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


class OAuthMixin:
    """Mixin for OAuth-based sources"""

    def get_oauth_integration(self, integration_id: str, team_id: int) -> Integration:
        """Get OAuth integration from integration ID"""
        if not integration_id:
            raise ValueError(f"Missing integration ID")

        if not Integration.objects.filter(id=integration_id, team_id=team_id).exists():
            raise ValueError(f"Integration not found: {integration_id}")

        return Integration.objects.get(id=integration_id, team_id=team_id)
