"""Django app configuration for agent_platform."""

from django.apps import AppConfig
from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)


class AgentPlatformConfig(AppConfig):
    name = "products.agent_platform.backend"
    label = "agent_platform"

    def ready(self) -> None:
        # Operators-facing nudge: when the signing key is unset outside
        # DEBUG, every Django→janitor call will 401 (the client skips the
        # JWT mint, the janitor rejects the missing header). Log loudly at
        # startup so the misconfiguration is caught before the first
        # authoring request lands rather than via a flood of 401 traces.
        if not settings.DEBUG and not settings.AGENT_INTERNAL_SIGNING_KEY:
            logger.warning(
                "agent_platform_internal_signing_key_unset",
                hint="Set AGENT_INTERNAL_SIGNING_KEY (32+ bytes from `openssl rand -hex 32`). "
                "Django→janitor calls will 401 until configured.",
            )
