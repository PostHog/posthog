from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.conversations.backend"
    label = "conversations"
    verbose_name = "Conversations"

    def ready(self):
        from . import signals  # noqa: F401
