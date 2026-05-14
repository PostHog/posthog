"""Django app configuration for agentic_tests."""

from django.apps import AppConfig


class AgenticTestsConfig(AppConfig):
    name = "products.agentic_tests.backend"
    label = "agentic_tests"

    def ready(self) -> None:
        from products.agentic_tests.backend.signals import register_task_run_signal

        register_task_run_signal()
