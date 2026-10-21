from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.conversations.backend"
    label = "conversations"
    verbose_name = "Support"

    def ready(self) -> None:
        from . import signals  # noqa: F401
        from .learning_provider import register_conversations_learning_provider

        register_conversations_learning_provider()
