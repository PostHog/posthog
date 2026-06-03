"""Django app configuration for agent_platform."""

from django.apps import AppConfig


class AgentPlatformConfig(AppConfig):
    name = "products.agent_platform.backend"
    label = "agent_platform"

    def ready(self) -> None:
        # Bind activity-log signal receivers for AgentApplication and
        # AgentRevision. Django's standard pattern: import inside `ready()`
        # so the decorators register after the app registry is ready.
        from . import activity  # noqa: F401, PLC0415
