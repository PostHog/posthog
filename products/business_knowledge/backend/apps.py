"""Django app configuration for business_knowledge."""

from django.apps import AppConfig


class BusinessKnowledgeConfig(AppConfig):
    name = "products.business_knowledge.backend"
    label = "business_knowledge"
    verbose_name = "Business knowledge"

    def ready(self) -> None:
        from . import signals  # noqa: F401
