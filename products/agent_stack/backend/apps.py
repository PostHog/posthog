"""Django app configuration for agent_stack."""

from django.apps import AppConfig


class AgentStackConfig(AppConfig):
    name = "products.agent_stack.backend"
    label = "agent_stack"

    def ready(self) -> None:
        # Bind signal receivers (activity log + the change feed) for
        # AgentApplication / AgentRevision. Django's standard pattern: import
        # inside `ready()` so the decorators register after the app registry
        # is ready.
        from . import activity, change_feed  # noqa: F401, PLC0415
