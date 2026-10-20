from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.conversations.backend"
    label = "conversations"
    verbose_name = "Support"

    def ready(self) -> None:
        from products.tasks.backend.facade.profiles import register_task_profiles

        from . import signals, task_profiles  # noqa: F401
        from .learning_provider import register_conversations_learning_provider

        register_task_profiles(task_profiles.PROFILES)
        register_conversations_learning_provider()
