from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        from products.customer_analytics.backend import signals  # noqa: F401, PLC0415 — receiver wiring only
