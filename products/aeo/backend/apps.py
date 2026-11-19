from django.apps import AppConfig


class AEOConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.aeo.backend"
    label = "aeo"

    def ready(self) -> None:
        from products.aeo.backend import signals  # noqa: F401, PLC0415 -- registration belongs at app population
