from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.conversations.backend"
    label = "conversations"
    verbose_name = "Support"

    def ready(self):
        from . import presence_access, signals  # noqa: F401

        presence_access.register()
