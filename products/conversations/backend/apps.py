from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.conversations.backend"
    label = "conversations"
    verbose_name = "Support"

    def ready(self) -> None:
        # The activity receiver only runs in processes that import it. ready() is that import.
        from . import (
            activity_logging,  # noqa: F401, PLC0415
            signals,  # noqa: F401
            task_profiles,
        )
        from .learning_provider import register_conversations_learning_provider

        register_conversations_learning_provider()
        task_profiles.register()

        from products.signals.backend.facade.agent_sources import register_agent_source  # noqa: PLC0415

        # Dotted paths, so the handlers and the Self-driving code they call load only when a ticket runs.
        register_agent_source(
            agent="research",
            product="conversations",
            type="ticket",
            load="products.conversations.backend.self_driving.load_ticket_for_agent",
            on_result="products.conversations.backend.self_driving.on_agent_run_result",
            on_fix_run_ended="products.conversations.backend.self_driving.on_fix_run_ended",
        )
