"""Django app configuration for commands."""

from django.apps import AppConfig


class CommandsConfig(AppConfig):
    name = "products.commands.backend"
    label = "commands"

    def ready(self) -> None:
        from products.commands.backend import receivers  # noqa: PLC0415 — needs the app registry

        receivers.connect()
