from django.apps import AppConfig


class BetsConfig(AppConfig):
    name = "products.bets.backend"
    label = "bets"
    verbose_name = "Bets"

    def ready(self) -> None:
        from . import activity_logging  # noqa: F401, PLC0415 — connect audit logging in every process
        from .receivers import connect_receivers  # noqa: PLC0415 — register receivers after all product models load

        connect_receivers()
