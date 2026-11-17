"""Django app configuration for ai_gateway."""

from django.apps import AppConfig


class AiGatewayConfig(AppConfig):
    name = "products.ai_gateway.backend"
    label = "ai_gateway"

    def ready(self) -> None:
        # Deactivation happens in web, SCIM and workers, so the receiver connects in every process.
        from products.ai_gateway.backend import receivers  # noqa: PLC0415 — needs the app registry

        receivers.connect()
