"""Django app configuration for agent_memory."""

from django.apps import AppConfig


class AgentMemoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.agent_memory.backend"
    label = "agent_memory"
    verbose_name = "Agent memory"
